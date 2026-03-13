#!/usr/bin/env python3
"""
Boson RAG API Server — 搜尋引擎後台
核心原理：常駐模型於記憶體，提供高速搜尋接口
"""

import socket
import os
import sys
import json
import time
import signal
import logging
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from threading import Lock
from datetime import datetime
from pathlib import Path
from io import StringIO

# ============================================================
# 動態路徑與配置 (自動偵測當前目錄)
# ============================================================
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# 匯入設定
from config import LOG_PATH, DEFAULT_HOST, DEFAULT_PORT

PID_FILE = "/tmp/boson_server.pid"

# ============================================================
# 日誌設定
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("boson-server")

class AppState:
    def __init__(self):
        self.ready = False
        self.start_time = None
        self.request_count = 0
        self.error_count = 0
        self.lock = Lock()
        self.query_module = None

state = AppState()

def load_engine():
    """載入 query 模組並預熱語義模型"""
    logger.info("⏳ 正在啟動 Boson RAG 搜尋引擎...")
    t0 = time.time()
    os.chdir(str(BASE_DIR))

    try:
        # 修正：匯入改名後的 boson_query 避免名稱衝突
        import boson_query as query_module
        state.query_module = query_module
        query_module._get_model_and_collection()
        
        state.ready = True
        state.start_time = datetime.now()
        logger.info(f"🚀 Boson RAG 服務就緒！載入耗時: {time.time() - t0:.2f}s")
    except Exception as e:
        logger.error(f"❌ 引擎載入失敗: {e}")
        sys.exit(1)

def do_search(query_str, mode="search", top_k=5):
    """執行搜尋並擷取輸出"""
    if not state.ready:
        return {"success": False, "error": "服務正在初始化中"}
    
    state.request_count += 1
    logger.info(f"🔍 搜尋請求 [{mode}]: {query_str}")
    
    old_stdout = sys.stdout
    sys.stdout = mystdout = StringIO()
    
    try:
        state.query_module.search(query_str, mode=mode)
        output = mystdout.getvalue()
        return {
            "success": True,
            "mode": mode,
            "query": query_str,
            "raw_output": output,
            "search_time": f"{time.time():.2f}"
        }
    except Exception as e:
        state.error_count += 1
        return {"success": False, "error": str(e)}
    finally:
        sys.stdout = old_stdout

class BosonHandler(BaseHTTPRequestHandler):
    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({
                "service": "Boson RAG API",
                "status": "healthy" if state.ready else "loading",
                "uptime": str(datetime.now() - state.start_time) if state.start_time else "0",
                "pid": os.getpid()
            })
        elif parsed.path == "/search":
            params = parse_qs(parsed.query)
            q = params.get("q", [None])[0]
            mode = params.get("mode", ["search"])[0]
            if not q:
                self._send_json({"success": False, "error": "缺少查詢參數 q"}, 400)
                return
            result = do_search(q, mode)
            self._send_json(result)
        elif parsed.path == "/cache/clear":
            if state.query_module:
                state.query_module._CACHE_FILE.unlink(missing_ok=True)
                self._send_json({"success": True, "message": "Boson 快取已清除"})

def run_server(host, port):
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    load_engine()
    server = HTTPServer((host, port), BosonHandler)
    logger.info(f"🌐 Boson API 啟動於 http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", nargs="?", default="start")
    args = parser.parse_args()
    if args.action == "start":
        run_server(DEFAULT_HOST, DEFAULT_PORT)
    elif args.action == "stop":
        if os.path.exists(PID_FILE):
            with open(PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
