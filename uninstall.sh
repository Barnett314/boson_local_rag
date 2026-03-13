#!/bin/bash

# 自動偵測腳本當前所在的目錄
INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${CYAN}🛑 開始解除安裝 Boson RAG System...${NC}"
echo "========================================="

# 1. 停止並移除背景服務 (加上 2>/dev/null 忽略找不到服務的錯誤)
echo "⚙️ 停止並移除系統服務..."
sudo systemctl stop boson-rag.service 2>/dev/null
sudo systemctl disable boson-rag.service 2>/dev/null
sudo rm -f /etc/systemd/system/boson-rag.service
sudo systemctl daemon-reload
echo -e "${GREEN}✅ 系統服務已移除${NC}"

# 2. 移除全域指令捷徑
echo "🔗 移除全域指令捷徑 (br)..."
sudo rm -f /usr/local/bin/br
echo -e "${GREEN}✅ br 指令已移除${NC}"

# 3. 移除自動排程
echo "⏰ 移除每日更新排程..."
(crontab -l 2>/dev/null | grep -v "daily_index.sh") | crontab - 2>/dev/null
echo -e "${GREEN}✅ 排程已移除${NC}"

echo "========================================="

# 4. 詢問是否清除資料庫與快取
read -p "🗑️ 是否要清除向量資料庫 (ChromaDB) 與快取檔案？(y/N): " purge_db
if [[ "$purge_db" =~ ^[Yy]$ ]]; then
    rm -rf "$INSTALL_DIR/chroma_db"
    rm -f "$INSTALL_DIR/.hash_cache.json"
    rm -f "$INSTALL_DIR/query_cache.json"
    echo -e "${GREEN}✅ 資料庫與快取已清除。${NC}"
else
    echo -e "${YELLOW}⏭️ 保留資料庫與快取。${NC}"
fi

# 5. 詢問是否清除整個專案原始碼
echo "========================================="
echo -e "${RED}⚠️ 警告：這將會刪除整個虛擬環境 (.venv) 與所有 Python 原始碼檔案！${NC}"
read -p "💥 是否要徹底刪除專案資料夾 ($INSTALL_DIR)？(y/N): " purge_src
if [[ "$purge_src" =~ ^[Yy]$ ]]; then
    echo "🧹 正在刪除原始碼目錄..."
    # 離開當前目錄以避免刪除自己時卡住
    cd ~ 
    rm -rf "$INSTALL_DIR"
    echo -e "${GREEN}✅ 專案原始碼已徹底清除。${NC}"
else
    echo -e "${YELLOW}⏭️ 保留專案原始碼。${NC}"
fi

echo "========================================="
echo -e "${CYAN}🎉 Boson RAG 解除安裝程序結束。${NC}"
