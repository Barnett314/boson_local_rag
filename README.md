# 🤖 Boson RAG System
Boson 的個人專屬知識檢索系統。

## 🚀 安裝方式

```bash
git clone https://github.com/Barnett314/boson_local_rag.git
cd boson_local_rag
bash install.sh
```

或一行安裝：

```bash
curl -fsSL https://raw.githubusercontent.com/Barnett314/boson_local_rag/main/install.sh -o install.sh && bash install.sh
```
## 🔍 指令速查
- `br find "關鍵字"` : 語意搜尋。
- `br ask "問題"` : AI 根據筆記回答。
- `br match "文字"` : 精確字串搜尋。
- `br clean` : 更新筆記後手動清除快取。
- `br status` : 檢查服務是否健康。

## ⚙️ 維護
- **索引更新**：每日 03:00 自動執行。
- **環境管理**：由 `install.sh` 自動化配置 。
