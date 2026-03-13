import typer
import subprocess
import os
import json
import hashlib
from pathlib import Path
from sentence_transformers import SentenceTransformer
import chromadb
from config import *

app = typer.Typer()

# ──────────────────────────────────────────────
# 全域快取：模型只載入一次（互動模式用）
# ──────────────────────────────────────────────
_model = None
_collection = None

def _get_model_and_collection():
    global _model, _collection
    if _model is None:
        print("⏳ 載入模型中...", end="", flush=True)
        _model = SentenceTransformer(EMBEDDING_MODEL)
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        # 關鍵修改：使用 get_or_create_collection 防止首次啟動或空資料庫崩潰
        _collection = client.get_or_create_collection("vault")
        print(" ✅ 就緒")
    return _model, _collection

# ──────────────────────────────────────────────
# 查詢快取：基於來源檔案 mtime，改了就失效
# ──────────────────────────────────────────────
_CACHE_FILE = Path(CHROMA_PATH) / "query_cache.json"

def _load_cache() -> dict:
    if _CACHE_FILE.exists():
        try:
            return json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def _save_cache(cache: dict):
    try:
        _CACHE_FILE.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
    except Exception:
        pass

def _cache_key(query: str, mode: str) -> str:
    return hashlib.md5(f"{query}|{mode}".encode()).hexdigest()

def _source_mtime(source_paths: list) -> float:
    # 支援多重絕對路徑的修改
    mtimes = []
    for p in source_paths:
        path_obj = Path(p)
        if path_obj.exists():
            mtimes.append(path_obj.stat().st_mtime)
    return max(mtimes) if mtimes else 0.0

def _cache_get(query: str, mode: str):
    cache = _load_cache()
    key = _cache_key(query, mode)
    entry = cache.get(key)
    if not entry:
        return None
    current_mtime = _source_mtime(entry.get("source_files", []))
    if current_mtime > entry.get("mtime", 0):
        return None  # 來源檔案已更新，快取失效
    return entry

def _cache_set(query: str, mode: str, answer: str, filenames: list):
    cache = _load_cache()
    key = _cache_key(query, mode)
    cache[key] = {
        "answer": answer,
        "source_files": filenames,
        "mtime": _source_mtime(filenames),
    }
    _save_cache(cache)

# ──────────────────────────────────────────────
# 段落組裝：不硬切字元，優先在段落邊界截斷
# ──────────────────────────────────────────────
def _trim_to_paragraphs(text: str, max_chars: int = 1200) -> str:
    if len(text) <= max_chars:
        return text
    for sep in ["\n\n", "。", "\n"]:
        idx = text.rfind(sep, 0, max_chars)
        if idx > max_chars // 2:
            return text[:idx + len(sep)]
    return text[:max_chars]

def extract_clean_snippet(text: str, max_len: int = 300) -> str:
    """
    提取乾淨的 snippet，跳過程式碼區塊開頭 ````
    """
    if not text:
        return ""
    
    lines = text.split('\n')
    clean_lines = []
    
    for line in lines:
        stripped = line.strip()
        # 跳過程式碼區塊開頭 ````
        if stripped.startswith('```'):
            continue
        # 跳過空行
        if not stripped:
            continue
        clean_lines.append(line)
    
    # 如果所有行都被過濾掉了，返回原始文本的前 max_len 字元
    if not clean_lines:
        return text[:max_len]
    
    # 重新組合並截取
    clean_text = ' '.join(clean_lines).strip()
    return clean_text[:max_len]

def _build_context(documents: list) -> str:
    parts = []
    for doc in documents:
        parts.append(_trim_to_paragraphs(doc))
    return "\n\n---\n\n".join(parts)

# ──────────────────────────────────────────────
# 核心搜尋
# ──────────────────────────────────────────────
def _semantic_search(query: str):
    model, collection = _get_model_and_collection()
    vec = model.encode([query], normalize_embeddings=True).tolist()
    results = collection.query(
        query_embeddings=vec,
        n_results=TOP_K,
        include=["documents", "metadatas", "distances"]
    )
    return results

def _grep_files(query: str) -> list:
    try:
        # 將所有 VAULT_PATHS 一起傳給 rg (ripgrep 天生支援多路徑搜尋)
        cmd = ["rg", "-l", query] + VAULT_PATHS
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        return result.stdout.strip().splitlines()
    except Exception:
        return []

# ──────────────────────────────────────────────
# Token 估算（粗估：4字元 ≈ 1 token）
# ──────────────────────────────────────────────
def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

# ──────────────────────────────────────────────
# 主指令
# ──────────────────────────────────────────────
@app.command()
def search(
    query: str = typer.Argument(..., help="搜尋關鍵字或語意描述"),
    mode: str = typer.Option("search", help="grep | search | full"),
):
    # ── grep 模式 ──────────────────────────────
    if mode == "grep":
        subprocess.run(["rg", "-l", query] + VAULT_PATHS)
        return

    # ── search / full 共用：先查快取 ───────────
    cached = _cache_get(query, mode)
    if cached:
        print("⚡ 快取命中（來源檔案未變更）")
        print(cached["answer"])
        return

    # ── 語意搜尋 ──────────────────────────────
    try:
        results = _semantic_search(query)
    except Exception as e:
        print(f"❌ ChromaDB 搜尋失敗：{e}")
        print("🔄 降級到 grep 搜尋：")
        subprocess.run(["rg", "-l", query] + VAULT_PATHS)
        return

    # 處理空查詢結果
    if not results or not results["documents"] or not results["documents"][0]:
        print("⚠️ 知識庫中尚未建立索引，請先執行 `br index`")
        return

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]
    
    # 改為抓取絕對路徑 (source) 交給快取機制判斷，支援多重路徑
    filenames = [m.get("source", "") for m in metadatas]

    # L2 距離轉相似度分數（0~1，越高越相似）
    scores = [1 / (1 + d) for d in distances]
    best_score = scores[0] if scores else 0

    # ── search 模式 ────────────────────────────
    if mode == "search":
        answer_lines = []
        for doc, meta, score in zip(documents, metadatas, scores):
            line = f"\n📄 {meta.get('filename', '未知')} (相似度 {score:.2f})\n{extract_clean_snippet(doc, 300)}"
            answer_lines.append(line)
        answer = "\n".join(answer_lines)
        print(answer)
        _cache_set(query, mode, answer, filenames)
        return

    # ── full 模式 ──────────────────────────────
    if mode == "full":
        SCORE_THRESHOLD = 0.82  # 分數夠高 → 直接回傳，不呼叫 LLM
        
        if best_score >= SCORE_THRESHOLD:
            print(f"✅ 相似度 {best_score:.2f} ≥ {SCORE_THRESHOLD}，直接回傳（省 Token）\n")
            answer_lines = []
            for doc, meta, score in zip(documents, metadatas, scores):
                line = f"📄 {meta.get('filename', '未知')} (相似度 {score:.2f})\n{extract_clean_snippet(doc, 600)}"
                answer_lines.append(line)
            answer = "\n\n".join(answer_lines)
            print(answer)
            _cache_set(query, mode, answer, filenames)
            return

        # 分數不夠 → 呼叫 LLM
        if not DEEPSEEK_API_KEY:
            print("⚠️ 未設定 DEEPSEEK_API_KEY，顯示原始搜尋結果：")
            for doc, meta, score in zip(documents, metadatas, scores):
                print(f"\n📄 {meta.get('filename', '未知')} (相似度 {score:.2f})\n{extract_clean_snippet(doc, 300)}")
            return

        context = _build_context(documents)
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
            
            prompt = f"根據以下筆記內容回答問題，請用繁體中文回答：\n\n{context}\n\n問題：{query}"
            prompt_tokens = _estimate_tokens(prompt)
            
            resp = llm.invoke([HumanMessage(content=prompt)])
            answer = resp.content
            
            answer_tokens = _estimate_tokens(answer)
            total_tokens = prompt_tokens + answer_tokens
            
            print(f"📊 輸入約 {prompt_tokens} tokens，輸出約 {answer_tokens} tokens，合計約 {total_tokens} tokens")
            print("\n" + "="*50)
            print(answer)
            print("="*50)
            
            _cache_set(query, mode, answer, filenames)
            
        except Exception as e:
            print(f"❌ LLM 呼叫失敗：{e}")
            print("🔄 降級到語意搜尋結果：")
            for doc, meta, score in zip(documents, metadatas, scores):
                print(f"\n📄 {meta.get('filename', '未知')} (相似度 {score:.2f})\n{extract_clean_snippet(doc, 300)}")

# ──────────────────────────────────────────────
# 互動模式
# ──────────────────────────────────────────────
@app.command()
def interactive():
    """互動模式：模型只載入一次，可切換搜尋模式"""
    print("🤖 Boson RAG 互動模式")
    print("指令：")
    print("  :grep [關鍵詞]    - 全文搜尋")
    print("  :search [關鍵詞]  - 語意搜尋")
    print("  :full [關鍵詞]    - 完整回答")
    print("  :quit / :exit     - 離開")
    print("  :help             - 顯示說明")
    print()
    
    # 預先載入模型（只載一次）
    _get_model_and_collection()
    
    while True:
        try:
            user_input = input("🔍 查詢：").strip()
            if not user_input:
                continue
                
            if user_input.lower() in [":quit", ":exit", ":q"]:
                print("👋 再見！")
                break
                
            if user_input.lower() == ":help":
                print("🤖 Boson RAG 互動模式")
                print("指令：")
                print("  :grep [關鍵詞]    - 全文搜尋")
                print("  :search [關鍵詞]  - 語意搜尋")
                print("  :full [關鍵詞]    - 完整回答")
                print("  :quit / :exit     - 離開")
                print("  :help             - 顯示說明")
                continue
            
            # 解析模式
            if user_input.startswith(":grep "):
                mode = "grep"
                query = user_input[6:].strip()
            elif user_input.startswith(":search "):
                mode = "search"
                query = user_input[8:].strip()
            elif user_input.startswith(":full "):
                mode = "full"
                query = user_input[6:].strip()
            else:
                # 預設使用 full 模式
                mode = "full"
                query = user_input
            
            if not query:
                print("⚠️ 請輸入查詢關鍵詞")
                continue
            
            # 執行搜尋
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
