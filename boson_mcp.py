#!/usr/bin/env python3
"""
Boson RAG MCP Server
讓 Claude Code 直接把你的 Obsidian 筆記當工具用。

前置條件：Boson 服務必須先啟動（br service start）
"""
import httpx
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "Boson RAG",
    instructions=(
        "查詢 Boson 的個人 Obsidian 知識庫。"
        "服務須先啟動：br service start。"
        "優先用 boson_ask 做 How-to 問題，boson_find 找相關筆記，boson_match 找精確關鍵字。"
    ),
)

BASE = "http://127.0.0.1:8900"
TIMEOUT = 30.0


def _get(path: str, params: dict | None = None) -> dict:
    try:
        r = httpx.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        return {"success": False, "error": "Boson 服務未啟動，請先執行 `br service start`"}
    except Exception as e:
        return {"success": False, "error": str(e)}


@mcp.tool()
def boson_find(query: str) -> str:
    """
    語意搜尋筆記，回傳最相關的片段與來源檔名。
    適合：「有沒有關於 X 的筆記」、「哪篇筆記提到 Y」
    """
    data = _get("/search", {"q": query, "mode": "search"})
    if data.get("success"):
        return data.get("raw_output") or "（無相關結果）"
    return f"❌ {data.get('error')}"


@mcp.tool()
def boson_ask(question: str) -> str:
    """
    根據筆記內容回答問題，AI 會整合多篇筆記後作答，並帶入近期對話脈絡。
    適合：具體操作問題、How-to、「怎麼設定 X」
    """
    data = _get("/search", {"q": question, "mode": "full"})
    if data.get("success"):
        return data.get("raw_output") or "（無相關結果）"
    return f"❌ {data.get('error')}"


@mcp.tool()
def boson_match(keyword: str) -> str:
    """
    精確字串搜尋，列出包含關鍵字的筆記檔名。
    適合：指令名稱、型號、設定參數、port 號碼等需要完全吻合的詞彙
    """
    data = _get("/search", {"q": keyword, "mode": "grep"})
    if data.get("success"):
        return data.get("raw_output") or "（無符合檔案）"
    return f"❌ {data.get('error')}"


@mcp.tool()
def boson_status() -> str:
    """檢查 Boson 服務是否運行中，回傳 uptime 與狀態"""
    data = _get("/health")
    if not data.get("error"):
        status = data.get("status", "unknown")
        uptime = data.get("uptime", "-")
        return f"✅ 服務狀態：{status}，已運行：{uptime}"
    return f"❌ {data.get('error')}"


@mcp.tool()
def boson_history() -> str:
    """查看最近 20 筆 ask 問答記錄，了解先前查詢過的內容"""
    data = _get("/history")
    if data.get("success"):
        items = data.get("history", [])
        if not items:
            return "（尚無對話記錄）"
        return "\n".join(f"[{h['ts']}] {h['query']}" for h in items)
    return f"❌ {data.get('error')}"


if __name__ == "__main__":
    mcp.run()
