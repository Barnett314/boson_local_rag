import typer
import subprocess
import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
from sentence_transformers import SentenceTransformer
import chromadb
from config import *

app = typer.Typer()

# ── 全域快取 ──────────────────────────────────────────
_model = None
_collection = None
_reranker = None          # CrossEncoder 或 False（載入失敗）
_bm25_data = None         # {"ids", "id2doc", "id2meta", "ids_list", "docs_list", "index"}

def _get_model_and_collection():
    global _model, _collection
    if _model is None:
        print("⏳ 載入模型中...", end="", flush=True)
        _model = SentenceTransformer(EMBEDDING_MODEL)
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = client.get_or_create_collection("vault")
        print(" ✅ 就緒")
    return _model, _collection

def _get_reranker():
    global _reranker
    if _reranker is False:
        return None
    if _reranker is None:
        try:
            from sentence_transformers import CrossEncoder
            print("⏳ 載入 Reranker 中...", end="", flush=True)
            _reranker = CrossEncoder(RERANK_MODEL)
            print(" ✅ 就緒")
        except Exception as e:
            print(f" ⚠️ Reranker 無法載入，改用 RRF 排序：{e}")
            _reranker = False
            return None
    return _reranker

def _get_bm25():
    global _bm25_data
    if _bm25_data is None:
        try:
            from rank_bm25 import BM25Okapi
            _, col = _get_model_and_collection()
            result = col.get(include=["documents", "metadatas"])
            ids  = result.get("ids", [])
            docs = result.get("documents", [])
            metas= result.get("metadatas", [])
            if docs:
                _bm25_data = {
                    "ids_list":  ids,
                    "id2doc":    dict(zip(ids, docs)),
                    "id2meta":   dict(zip(ids, metas)),
                    "index":     BM25Okapi([d.split() for d in docs]),
                }
        except Exception:
            _bm25_data = {}
    return _bm25_data or {}

def _reset_bm25():
    global _bm25_data
    _bm25_data = None

# ── 查詢快取（基於來源檔案 mtime）────────────────────
_CACHE_FILE = Path(CHROMA_PATH) / "query_cache.json"

def _load_cache():
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_cache(cache):
    try:
        _CACHE_FILE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

def _cache_key(query, mode):
    return hashlib.md5(f"{query}|{mode}".encode()).hexdigest()

def _source_mtime(source_paths):
    mtimes = [Path(p).stat().st_mtime for p in source_paths if Path(p).exists()]
    return max(mtimes) if mtimes else 0.0

def _cache_get(query, mode):
    cache = _load_cache()
    entry = cache.get(_cache_key(query, mode))
    if not entry:
        return None
    if _source_mtime(entry.get("source_files", [])) > entry.get("mtime", 0):
        return None
    return entry

def _cache_set(query, mode, answer, filenames):
    cache = _load_cache()
    cache[_cache_key(query, mode)] = {
        "answer": answer,
        "source_files": filenames,
        "mtime": _source_mtime(filenames),
    }
    _save_cache(cache)

# ── 對話歷史 ─────────────────────────────────────────
def _load_history():
    p = Path(HISTORY_FILE)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []

def _save_history(history):
    try:
        Path(HISTORY_FILE).write_text(
            json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass

def _append_history(query, mode, answer):
    history = _load_history()
    history.append({
        "ts":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "query":  query,
        "mode":   mode,
        "answer": answer[:500],
    })
    _save_history(history[-HISTORY_MAX:])

def _build_history_context():
    """取最近幾筆 full-mode 對話，組成 LLM prompt 前置文字"""
    recent = [h for h in _load_history() if h.get("mode") == "full"][-HISTORY_CONTEXT:]
    if not recent:
        return ""
    lines = ["【近期對話記錄（如與本次問題無關可忽略）】"]
    for h in recent:
        lines.append(f"Q：{h['query']}")
        lines.append(f"A：{h['answer'][:200]}")
        lines.append("")
    return "\n".join(lines) + "\n---\n"

# ── 文字處理 ─────────────────────────────────────────
def _trim_to_paragraphs(text, max_chars=1200):
    if len(text) <= max_chars:
        return text
    for sep in ["\n\n", "。", "\n"]:
        idx = text.rfind(sep, 0, max_chars)
        if idx > max_chars // 2:
            return text[:idx + len(sep)]
    return text[:max_chars]

def extract_clean_snippet(text, max_len=300):
    if not text:
        return ""
    lines = [l for l in text.split('\n') if l.strip() and not l.strip().startswith('```')]
    clean = ' '.join(lines).strip()
    return clean[:max_len] if clean else text[:max_len]

def _build_context(documents):
    return "\n\n---\n\n".join(_trim_to_paragraphs(d) for d in documents)

def _estimate_tokens(text):
    return max(1, len(text) // 4)

# ── Hybrid Search（向量 + BM25 RRF + Reranker）───────
def _hybrid_search(query):
    """
    1. 向量搜尋廣撈 TOP_K_RETRIEVE
    2. BM25 搜尋廣撈 TOP_K_RETRIEVE（需 rank-bm25，無則跳過）
    3. RRF 融合兩路結果
    4. CrossEncoder Reranker 精排（需 bge-reranker，無則直接用 RRF 排序）
    5. 回傳 TOP_K 筆
    """
    model, collection = _get_model_and_collection()
    n_total = collection.count()
    if n_total == 0:
        return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    n_retrieve = min(TOP_K_RETRIEVE, n_total)

    # 向量搜尋
    qvec = model.encode([query], normalize_embeddings=True).tolist()
    vec_r = collection.query(
        query_embeddings=qvec,
        n_results=n_retrieve,
        include=["documents", "metadatas", "distances", "ids"],
    )
    vec_ids   = vec_r["ids"][0]
    vec_docs  = vec_r["documents"][0]
    vec_meta  = vec_r["metadatas"][0]
    vec_dists = vec_r["distances"][0]

    # id → (doc, meta, dist) 快查表
    id2data = {
        id_: (doc, meta, dist)
        for id_, doc, meta, dist in zip(vec_ids, vec_docs, vec_meta, vec_dists)
    }

    # RRF 初始化（向量排名）
    rrf = {}
    for rank, id_ in enumerate(vec_ids):
        rrf[id_] = rrf.get(id_, 0) + 1 / (60 + rank + 1)

    # BM25 加入 RRF
    bm25 = _get_bm25()
    if bm25.get("index"):
        bm25_scores = bm25["index"].get_scores(query.split())
        ids_list = bm25["ids_list"]
        top_bm25 = sorted(range(len(bm25_scores)), key=lambda i: bm25_scores[i], reverse=True)[:n_retrieve]
        for rank, pos in enumerate(top_bm25):
            id_ = ids_list[pos]
            rrf[id_] = rrf.get(id_, 0) + 1 / (60 + rank + 1)
            if id_ not in id2data:
                id2data[id_] = (bm25["id2doc"][id_], bm25["id2meta"].get(id_, {}), 1.0)

    # 依 RRF 分數取前 n_retrieve 候選
    top_ids = sorted(rrf, key=rrf.get, reverse=True)[:n_retrieve]
    candidates = [(id2data[i][0], id2data[i][1], id2data[i][2]) for i in top_ids if i in id2data]

    if not candidates:
        return {
            "documents": [vec_docs[:TOP_K]],
            "metadatas": [vec_meta[:TOP_K]],
            "distances": [vec_dists[:TOP_K]],
        }

    # Reranker 精排
    reranker = _get_reranker()
    if reranker is not None:
        pairs  = [(query, doc) for doc, _, _ in candidates]
        scores = reranker.predict(pairs)
        ranked = sorted(zip(scores, candidates), key=lambda x: x[0], reverse=True)[:TOP_K]
        final_docs  = [doc  for _, (doc, _, _)  in ranked]
        final_meta  = [meta for _, (_, meta, _) in ranked]
        final_dists = [dist for _, (_, _, dist) in ranked]
    else:
        final_docs  = [doc  for doc, _, _  in candidates[:TOP_K]]
        final_meta  = [meta for _, meta, _ in candidates[:TOP_K]]
        final_dists = [dist for _, _, dist in candidates[:TOP_K]]

    return {
        "documents": [final_docs],
        "metadatas": [final_meta],
        "distances": [final_dists],
    }

# ── 主指令 ───────────────────────────────────────────
@app.command()
def search(
    query: str = typer.Argument(..., help="搜尋關鍵字或語意描述"),
    mode:  str = typer.Option("search", help="grep | search | full"),
):
    if mode == "grep":
        subprocess.run(["rg", "-l", query] + VAULT_PATHS)
        return

    cached = _cache_get(query, mode)
    if cached:
        print("⚡ 快取命中（來源檔案未變更）")
        print(cached["answer"])
        return

    try:
        results = _hybrid_search(query)
    except Exception as e:
        print(f"❌ 搜尋失敗：{e}")
        print("🔄 降級到 grep：")
        subprocess.run(["rg", "-l", query] + VAULT_PATHS)
        return

    if not results["documents"][0]:
        print("⚠️ 知識庫中尚未建立索引，請先執行 `br index`")
        return

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]
    filenames = [m.get("source", "") for m in metadatas]
    scores    = [1 / (1 + d) for d in distances]
    best_score = scores[0] if scores else 0

    # ── search 模式 ─────────────────────────────────
    if mode == "search":
        answer_lines = []
        for doc, meta, score in zip(documents, metadatas, scores):
            answer_lines.append(
                f"\n📄 {meta.get('filename', '未知')} (相似度 {score:.2f})\n{extract_clean_snippet(doc, 300)}"
            )
        answer = "\n".join(answer_lines)
        print(answer)
        _cache_set(query, mode, answer, filenames)
        return

    # ── full 模式 ───────────────────────────────────
    if mode == "full":
        SCORE_THRESHOLD = 0.6
        if best_score >= SCORE_THRESHOLD:
            print(f"✅ 相似度 {best_score:.2f} ≥ {SCORE_THRESHOLD}，直接回傳（省 Token）\n")
            answer_lines = []
            for doc, meta, score in zip(documents, metadatas, scores):
                answer_lines.append(
                    f"📄 {meta.get('filename', '未知')} (相似度 {score:.2f})\n{extract_clean_snippet(doc, 600)}"
                )
            answer = "\n\n".join(answer_lines)
            print(answer)
            _cache_set(query, mode, answer, filenames)
            _append_history(query, mode, answer)
            return

        if not DEEPSEEK_API_KEY:
            print("⚠️ 未設定 DEEPSEEK_API_KEY，顯示原始搜尋結果：")
            for doc, meta, score in zip(documents, metadatas, scores):
                print(f"\n📄 {meta.get('filename', '未知')} (相似度 {score:.2f})\n{extract_clean_snippet(doc, 300)}")
            return

        context    = _build_context(documents)
        hist_ctx   = _build_history_context()
        ctx_tokens = _estimate_tokens(context)
        print(f"📊 上下文約 {ctx_tokens} tokens，呼叫 LLM 中...")

        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.messages import HumanMessage

            llm = ChatOpenAI(
                model=DEEPSEEK_MODEL,
                api_key=DEEPSEEK_API_KEY,
                base_url=DEEPSEEK_BASE_URL,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
            )

            prompt = (
                f"{hist_ctx}"
                f"根據以下筆記內容回答問題，請用繁體中文回答：\n\n{context}\n\n問題：{query}"
            )
            prompt_tokens = _estimate_tokens(prompt)
            resp  = llm.invoke([HumanMessage(content=prompt)])
            answer = resp.content
            answer_tokens = _estimate_tokens(answer)

            print(f"📊 輸入約 {prompt_tokens} tokens，輸出約 {answer_tokens} tokens，合計約 {prompt_tokens + answer_tokens} tokens")
            print("\n" + "="*50)
            print(answer)
            print("="*50)

            _cache_set(query, mode, answer, filenames)
            _append_history(query, mode, answer)

        except Exception as e:
            print(f"❌ LLM 呼叫失敗：{e}")
            print("🔄 降級到語意搜尋結果：")
            for doc, meta, score in zip(documents, metadatas, scores):
                print(f"\n📄 {meta.get('filename', '未知')} (相似度 {score:.2f})\n{extract_clean_snippet(doc, 300)}")

# ── 互動模式 ──────────────────────────────────────────
@app.command()
def interactive():
    """互動模式：模型只載入一次，可切換搜尋模式"""
    print("🤖 Boson RAG 互動模式")
    print("  :grep <詞>    全文搜尋")
    print("  :search <詞>  語意搜尋")
    print("  :full <詞>    完整回答（帶對話歷史）")
    print("  :history      查看近期對話記錄")
    print("  :quit         離開")
    print()
    _get_model_and_collection()

    while True:
        try:
            user_input = input("🔍 查詢：").strip()
            if not user_input:
                continue

            if user_input.lower() in [":quit", ":exit", ":q"]:
                print("👋 再見！")
                break

            if user_input.lower() == ":history":
                history = _load_history()
                if not history:
                    print("（尚無對話記錄）")
                else:
                    for h in history[-10:]:
                        print(f"  [{h['ts']}] {h['query']}")
                continue

            if user_input.startswith(":grep "):
                mode, query = "grep", user_input[6:].strip()
            elif user_input.startswith(":search "):
                mode, query = "search", user_input[8:].strip()
            elif user_input.startswith(":full "):
                mode, query = "full", user_input[6:].strip()
            else:
                mode, query = "full", user_input

            if not query:
                print("⚠️ 請輸入查詢關鍵詞")
                continue

            print()
            search(query, mode)
            print()

        except KeyboardInterrupt:
            print("\n👋 再見！")
            break
        except Exception as e:
            print(f"❌ 錯誤：{e}")
            print()


if __name__ == "__main__":
    app()
