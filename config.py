import os
from pathlib import Path
from dotenv import load_dotenv

# 自動獲取當前檔案所在的絕對路徑
BASE_DIR = Path(__file__).resolve().parent

# 載入 .env 變數
load_dotenv(BASE_DIR / ".env")

# === 路徑設定：自動適應環境 ===
vault_paths_env = os.getenv("VAULT_PATHS", str(Path.home() / "Documents/KnowledgeBase"))
VAULT_PATHS = [p.strip() for p in vault_paths_env.split(",") if p.strip()]
CHROMA_PATH = str(BASE_DIR / "chroma_db")
HASH_CACHE = str(BASE_DIR / ".hash_cache.json")
LOG_PATH = str(BASE_DIR / "logs" / "index.log")

# === Embedding 模型 ===
EMBEDDING_MODEL = "BAAI/bge-m3"

# === DeepSeek 設定 ===
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_MODEL = "deepseek-chat"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# === 參數設定 ===
MAX_TOKENS = 2000
TEMPERATURE = 0.3
CHUNK_SIZE = 500
CHUNK_OVERLAP = 80
TOP_K = 5
TOP_K_RETRIEVE = 20
MAX_RETRIES = 3
RETRY_DELAY = 2

# === Hybrid 搜尋 ===
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"

# === 對話歷史 ===
HISTORY_FILE = str(BASE_DIR / ".conversation_history.json")
HISTORY_MAX = 30
HISTORY_CONTEXT = 3

# === 伺服器設定 ===
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8900
