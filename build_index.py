import os, json, hashlib, time, frontmatter
from pathlib import Path
from datetime import datetime
from sentence_transformers import SentenceTransformer
import chromadb
from langchain_text_splitters import MarkdownTextSplitter
from config import *

Path(LOG_PATH).parent.mkdir(parents=True, exist_ok=True)

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

def file_hash(path):
    return hashlib.md5(Path(path).read_bytes()).hexdigest()

def load_cache():
    if Path(HASH_CACHE).exists():
        return json.loads(Path(HASH_CACHE).read_text())
    return {}

def save_cache(cache):
    Path(HASH_CACHE).write_text(json.dumps(cache, indent=2))

def read_file_safe(fpath):
    """自動偵測編碼，支援 UTF-8 / BIG5"""
    for encoding in ["utf-8", "big5", "utf-8-sig", "cp950"]:
        try:
            return fpath.read_text(encoding=encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    log(f" ⚠️ 無法解碼：{fpath.name}，跳過")
    return None

def embed_with_retry(model, chunks):
    """帶重試機制的 Embedding，處理網路超時"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return model.encode(chunks, normalize_embeddings=True).tolist()
        except Exception as e:
            wait = RETRY_DELAY * (2 ** (attempt - 1))
            log(f" ⚠️ Embedding 失敗（第{attempt}次），{wait}秒後重試：{e}")
            time.sleep(wait)
    log(f" ❌ Embedding 重試{MAX_RETRIES}次仍失敗，跳過此批次")
    return None

def main():
    log("=== 開始建立索引 ===")
    log(f"Embedding 模型：{EMBEDDING_MODEL}")
    
    log("載入 bge-m3 模型（首次約 30 秒）...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_or_create_collection(
        name="vault",
        metadata={"hnsw:space": "cosine"}
    )
    
    cache = load_cache()
    splitter = MarkdownTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP
    )
    
    md_files = []
    for v_path in VAULT_PATHS:
        v_dir = Path(v_path)
        if v_dir.exists():
            md_files.extend(list(v_dir.rglob("*.md")))
        else:
            log(f" ⚠️ 找不到路徑，已跳過：{v_path}")
    
    added = skipped = empty = error = 0
    
    for fpath in md_files:
        fhash = file_hash(fpath)
        fkey = str(fpath)
        
        # 未變更跳過
        if cache.get(fkey) == fhash:
            skipped += 1
            continue
        
        # 空檔案跳過
        if fpath.stat().st_size == 0:
            log(f" ⏭️ 空檔案跳過：{fpath.name}")
            empty += 1
            continue
        
        # 讀取並偵測編碼
        raw = read_file_safe(fpath)
        if raw is None:
            error += 1
            continue
        
        try:
            # 嘗試解析 frontmatter，如果失敗則使用原始內容
            try:
                post = frontmatter.loads(raw)
                content = post.content.strip()
            except Exception as fm_error:
                log(f" ⚠️ Frontmatter 解析失敗 {fpath.name}，使用原始內容：{fm_error}")
                content = raw.strip()
            
            if not content:
                log(f" ⏭️ 無內容跳過：{fpath.name}")
                empty += 1
                continue
            
            chunks = splitter.split_text(content)
            embeddings = embed_with_retry(model, chunks)
            if embeddings is None:
                error += 1
                continue
            
            ids = [f"{fkey}::chunk{i}" for i in range(len(chunks))]
            
            try:
                collection.delete(where={"source": fkey})
            except Exception:
                pass
            
            collection.add(
                ids=ids,
                embeddings=embeddings,
                documents=chunks,
                metadatas=[{"source": fkey, "filename": fpath.name}] * len(chunks)
            )
            
            cache[fkey] = fhash
            added += 1
            log(f" ✅ {fpath.name}（{len(chunks)} chunks）")
            
        except Exception as e:
            log(f" ❌ 處理失敗 {fpath.name}：{e}")
            error += 1
    
    save_cache(cache)
    log(f"=== 完成 | 新增/更新：{added} | 跳過：{skipped} | 空檔：{empty} | 錯誤：{error} ===")

if __name__ == "__main__":
    main()
