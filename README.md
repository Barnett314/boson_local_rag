# Boson RAG System
Boson 的個人專屬知識檢索系統。把 Obsidian 筆記變成可以對話的本地 AI 知識庫。

## 安裝方式

```bash
git clone https://github.com/Barnett314/boson_local_rag.git
cd boson_local_rag
bash install.sh
```

## 設定筆記資料夾（必做）

安裝後複製範本並填入你的 Obsidian Vault 路徑：

```bash
cp .env.example .env
nano .env   # 或用任何編輯器開啟
```

`.env` 最少只需要設定這一行：

```
VAULT_PATHS=/Users/你的名字/Documents/MyVault
```

多個資料夾用逗號分隔：

```
VAULT_PATHS=/Users/你的名字/Obsidian/Work,/Users/你的名字/Obsidian/Personal
```

設定完後建立索引：

```bash
br index
```

## 指令速查

| 指令 | 說明 |
|------|------|
| `br find "關鍵字"` | 語意搜尋，找相關筆記片段 |
| `br ask "問題"` | AI 根據筆記回答，帶對話記憶 |
| `br match "文字"` | 精確字串搜尋（指令名稱、型號） |
| `br history` | 查看近期問答記錄 |
| `br index` | 手動更新索引 |
| `br clean` | 清除搜尋快取 |
| `br status` | 檢查服務健康狀態 |
| `br service start` | 啟動常駐服務（模型載入記憶體） |
| `br service stop` | 停止服務（釋放記憶體） |

## 硬體需求

| 項目 | 最低 | 建議 |
|------|------|------|
| RAM | 4 GB | 8 GB |
| 磁碟（模型） | 2 GB | 3 GB |
| CPU | 任意 | Apple Silicon / 多核心 |

> **說明**：`bge-m3` 嵌入模型約佔 1.5 GB RAM，`bge-reranker-v2-m3` 約佔 570 MB。
> 服務未啟動時 `br find` 每次冷啟動約需 15-30 秒載入模型；
> 啟動後（`br service start`）每次查詢約 0.5-2 秒。

## Claude Code MCP 整合（可選）

讓 Claude Code 直接把你的筆記當工具用，安裝時選「y」即可自動設定，或手動在 `~/.claude/settings.json` 加入：

```json
{
  "mcpServers": {
    "boson-rag": {
      "command": "/path/to/boson_local_rag/.venv/bin/python",
      "args": ["/path/to/boson_local_rag/boson_mcp.py"]
    }
  }
}
```

## 維護

- **索引更新**：每日 03:00 自動執行
- **換新筆記資料夾**：修改 `.env` 的 `VAULT_PATHS`，再執行 `br clean && br index`
