#!/bin/bash
# Boson RAG System - 完整安裝腳本 (v5.4)
# 支援：macOS (Homebrew + launchd) / Linux (apt / dnf + systemd)
# v5.4 修正：用 bash -c 包裝 ExecStart，原生支援中文/空格路徑

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
USER_NAME=$(whoami)
OS="$(uname -s)"
PLIST_LABEL="com.boson.rag"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
BR_BIN="/usr/local/bin/br"
VENV_PYTHON="$INSTALL_DIR/.venv/bin/python"

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
CYAN='\033[0;36m'
NC='\033[0m'

info()    { echo -e "${CYAN}ℹ️  $*${NC}"; }
success() { echo -e "${GREEN}✅ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠️  $*${NC}"; }
error()   { echo -e "${RED}❌ $*${NC}"; exit 1; }

echo -e "${CYAN}🚀 開始安裝 Boson RAG System${NC}"
echo    "   安裝目錄：$INSTALL_DIR"
echo    "   作業系統：$OS"
echo    "   執行使用者：$USER_NAME"
echo    "========================================="

# ==========================================
# 0. 專案檔案完整性檢查
# ==========================================
info "檢查專案檔案完整性..."
MISSING=false
for f in br boson_server.py boson_query.py build_index.py config.py daily_index.sh; do
    if [ ! -f "$INSTALL_DIR/$f" ]; then
        echo -e "${RED}   ✗ 缺少：$f${NC}"
        MISSING=true
    else
        echo -e "${GREEN}   ✓ 找到：$f${NC}"
    fi
done
[ "$MISSING" = true ] && error "專案檔案不完整，請確認下載是否正確。"

# ==========================================
# 1. 系統依賴安裝
# ==========================================
echo ""
info "安裝系統依賴..."

if [ "$OS" == "Darwin" ]; then
    echo "🍎 macOS 安裝流程"
    command -v brew &>/dev/null || error "找不到 Homebrew，請先安裝：https://brew.sh/"
    success "Homebrew：$(brew --version | head -1)"
    brew list python@3.11 &>/dev/null \
        && success "python@3.11 已存在，跳過" \
        || brew install python@3.11
    command -v rg &>/dev/null \
        && success "ripgrep 已存在，跳過" \
        || brew install ripgrep
    PYTHON_CMD="python3.11"

elif [ "$OS" == "Linux" ]; then
    echo "🐧 Linux 安裝流程"
    if command -v dnf &>/dev/null; then
        sudo dnf install -y python3.11 python3.11-venv ripgrep
    elif command -v apt-get &>/dev/null; then
        sudo apt-get update -qq
        sudo apt-get install -y python3.11 python3.11-venv ripgrep
    else
        warn "未知套件管理員，請確認已手動安裝 Python 3.11 與 ripgrep"
    fi
    PYTHON_CMD="python3.11"
else
    error "不支援的作業系統：$OS"
fi

command -v "$PYTHON_CMD" &>/dev/null || error "找不到 $PYTHON_CMD，請確認安裝是否成功"
success "Python 就緒：$($PYTHON_CMD --version)"
command -v rg &>/dev/null \
    && success "ripgrep 就緒：$(rg --version | head -1)" \
    || warn "找不到 rg，br match 指令將無法使用"

# ==========================================
# 2. 目錄與虛擬環境準備
# ==========================================
echo ""
info "建立必要目錄..."
mkdir -p "$INSTALL_DIR/logs" "$INSTALL_DIR/chroma_db"
success "目錄就緒：logs/、chroma_db/"

cd "$INSTALL_DIR"

if [ -d ".venv" ]; then
    warn ".venv 已存在，跳過重新建立（如需重建請先手動刪除 .venv/）"
else
    info "建立虛擬環境 (.venv)..."
    $PYTHON_CMD -m venv .venv
    success "虛擬環境建立完成"
fi

source .venv/bin/activate
success "虛擬環境已啟用：$(python --version)"

# ==========================================
# 3. 安裝 Python 套件
# ==========================================
echo ""
info "安裝 Python 套件（首次約需 3-5 分鐘）..."

cat <<'REQEOF' > requirements.txt
sentence-transformers
chromadb
langchain-text-splitters
python-frontmatter
python-dotenv
typer
rich
langchain-openai
langchain-core
requests
langchain-community
REQEOF

pip install --upgrade pip --quiet
pip install -r requirements.txt || error "套件安裝失敗，請檢查網路連線後重試"
success "所有 Python 套件安裝完成"

# ==========================================
# 4. 互動式 .env 設定
# ==========================================
echo ""
SETUP_ENV=true
FINAL_PROVIDER="deepseek"
FINAL_DS_KEY="YOUR_DEEPSEEK_KEY_HERE"
FINAL_OA_KEY="YOUR_OPENAI_KEY_HERE"

if [ -f ".env" ]; then
    echo -e "${YELLOW}⚠️  偵測到 .env 已存在。${NC}"
    read -rp "❓ 重新設定嗎？（舊檔案將備份為 .env.bak）[y/N]: " reconfig
    if [[ "$reconfig" =~ ^[Yy]$ ]]; then
        cp .env .env.bak
        success "舊設定已備份至 .env.bak"
        SETUP_ENV=true
    else
        SETUP_ENV=false
        success "保留現有 .env，跳過設定"
        FINAL_PROVIDER=$(awk -F= '/^LLM_PROVIDER=/{print $2}' .env | tr -d '[:space:]')
        FINAL_DS_KEY=$(awk -F= '/^DEEPSEEK_API_KEY=/{print $2}' .env | tr -d '[:space:]')
        FINAL_OA_KEY=$(awk -F= '/^OPENAI_API_KEY=/{print $2}' .env | tr -d '[:space:]')
    fi
fi

if [ "$SETUP_ENV" = true ]; then
    echo -e "\n${CYAN}📋 開始互動設定${NC}"
    echo    "========================================="

    echo -e "\n${CYAN}【步驟 1/3】設定知識庫路徑${NC}"
    DEFAULT_VAULT="$HOME/Documents/KnowledgeBase"
    read -rp "📂 筆記路徑（預設: $DEFAULT_VAULT）: " user_path
    VAULT_PATH="${user_path:-$DEFAULT_VAULT}"
    [ ! -d "$VAULT_PATH" ] \
        && warn "路徑 $VAULT_PATH 目前不存在，請安裝後建立" \
        || success "路徑存在：$VAULT_PATH"

    echo -e "\n${CYAN}【步驟 2/3】選擇 AI 供應商${NC}"
    echo    "   1) deepseek  2) openai  3) ollama"
    read -rp "🤖 選擇（1-3，Enter 選 1）: " brain_choice
    case "${brain_choice:-1}" in
        2) FINAL_PROVIDER="openai"   ;;
        3) FINAL_PROVIDER="ollama"   ;;
        *) FINAL_PROVIDER="deepseek" ;;
    esac
    success "已選擇：$FINAL_PROVIDER"

    OLLAMA_MODEL_VAL="llama3:8b"
    echo -e "\n${CYAN}【步驟 3/3】填入金鑰 / 模型設定${NC}"

    if [ "$FINAL_PROVIDER" == "deepseek" ]; then
        read -rp "🔑 DeepSeek API Key（Enter 稍後填）: " k
        FINAL_DS_KEY="${k:-$FINAL_DS_KEY}"
        [[ "$FINAL_DS_KEY" == *"YOUR_"* ]] && warn "未填入 Key" || success "Key 已設定"
    elif [ "$FINAL_PROVIDER" == "openai" ]; then
        read -rp "🔑 OpenAI API Key（Enter 稍後填）: " k
        FINAL_OA_KEY="${k:-$FINAL_OA_KEY}"
        [[ "$FINAL_OA_KEY" == *"YOUR_"* ]] && warn "未填入 Key" || success "Key 已設定"
    elif [ "$FINAL_PROVIDER" == "ollama" ]; then
        echo "   1) llama3:8b  2) llama3:70b  3) 自行輸入"
        read -rp "   選擇（Enter 選 1）: " om
        case "${om:-1}" in
            2) OLLAMA_MODEL_VAL="llama3:70b" ;;
            3) read -rp "   模型名稱: " OLLAMA_MODEL_VAL ;;
            *) OLLAMA_MODEL_VAL="llama3:8b"  ;;
        esac
        success "Ollama 模型：$OLLAMA_MODEL_VAL"
    fi

    info "產生 .env 設定檔..."
    cat <<EOF > .env
# === Boson RAG 環境變數設定 ===
VAULT_PATHS=$VAULT_PATH
LLM_PROVIDER=$FINAL_PROVIDER
DEEPSEEK_API_KEY=$FINAL_DS_KEY
OPENAI_API_KEY=$FINAL_OA_KEY
DEEPSEEK_MODEL=deepseek-chat
OPENAI_MODEL=gpt-4o
OLLAMA_MODEL=$OLLAMA_MODEL_VAL
OLLAMA_BASE_URL=http://localhost:11434
EOF
    success ".env 設定檔已產生！"
fi

# ==========================================
# 5. br 指令捷徑
# ==========================================
echo ""
info "設定 br 全域指令捷徑..."
chmod +x "$INSTALL_DIR/br"
chmod +x "$INSTALL_DIR/daily_index.sh"
if [ -L "$BR_BIN" ] || [ -f "$BR_BIN" ]; then
    sudo rm -f "$BR_BIN"
fi
sudo ln -sf "$INSTALL_DIR/br" "$BR_BIN"
success "br 指令已連結至 $BR_BIN"

# ==========================================
# 6. 系統服務註冊
# ==========================================
echo ""
info "註冊系統服務..."

if [ "$OS" == "Linux" ]; then

    # ── 關鍵修正 v5.4：用 bash -c 包裝 ExecStart ──
    # 讓 bash 處理路徑（支援中文、空格、特殊字元），
    # systemd 只需解析 /bin/bash 這個純 ASCII 路徑即可。
    # 路徑用雙引號包住，防止空格斷開；
    # 外層用單引號傳給 tee heredoc，防止 $ 被 bash 展開。
    sudo tee /etc/systemd/system/boson-rag.service > /dev/null <<EOF
[Unit]
Description=Boson RAG Search API Server
After=network.target

[Service]
Type=simple
User=$USER_NAME
WorkingDirectory=$INSTALL_DIR
ExecStart=/bin/bash -c 'exec "${VENV_PYTHON}" "${INSTALL_DIR}/boson_server.py" start'
Restart=on-failure
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

    sudo systemctl daemon-reload
    sudo systemctl enable boson-rag.service
    sudo systemctl restart boson-rag.service --no-block
    success "systemd 服務已啟動（支援中文路徑）"

    # 驗證 service 檔案寫入是否正確
    info "驗證 service 設定..."
    grep "ExecStart" /etc/systemd/system/boson-rag.service

elif [ "$OS" == "Darwin" ]; then
    info "產生 macOS launchd plist..."
    mkdir -p "$HOME/Library/LaunchAgents"

    # macOS plist 用 <string> 包住每個參數，天然支援中文路徑
    cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${VENV_PYTHON}</string>
        <string>${INSTALL_DIR}/boson_server.py</string>
        <string>start</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>${INSTALL_DIR}/logs/launchd.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>${INSTALL_DIR}/logs/launchd.stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
</dict>
</plist>
EOF
    launchctl list 2>/dev/null | grep -q "$PLIST_LABEL" \
        && launchctl unload -w "$PLIST_PATH" 2>/dev/null || true
    launchctl load -w "$PLIST_PATH" \
        && success "launchd 服務已載入" \
        || warn "launchd 載入失敗，請執行：launchctl load -w $PLIST_PATH"
fi

# ==========================================
# 7. 每日自動排程
# ==========================================
echo ""
info "設定每日 03:00 自動索引排程..."
(crontab -l 2>/dev/null | grep -v "daily_index.sh"; \
 echo "0 3 * * * \"$INSTALL_DIR/daily_index.sh\" >> \"$INSTALL_DIR/logs/cron.log\" 2>&1") \
 | crontab -
success "cron 排程已設定（每日 03:00）"

# ==========================================
# 8. 完成摘要
# ==========================================
KEY_WARNING=false
if [ "$FINAL_PROVIDER" != "ollama" ]; then
    [[ "$FINAL_DS_KEY" == *"YOUR_"* ]] && [[ "$FINAL_OA_KEY" == *"YOUR_"* ]] \
        && KEY_WARNING=true
fi

echo ""
echo "========================================="
success "安裝程序執行完畢！"
echo ""
echo -e "📁 安裝目錄：${CYAN}$INSTALL_DIR${NC}"
echo -e "⚙️  設定檔：  ${CYAN}$INSTALL_DIR/.env${NC}"
[ "$OS" == "Darwin" ] && echo -e "🍎 plist：   ${CYAN}$PLIST_PATH${NC}"
echo ""

if [ "$KEY_WARNING" = true ]; then
    echo -e "${YELLOW}⚠️  重要：尚未填入 API Key！${NC}"
    echo -e "   請執行：${CYAN}nano $INSTALL_DIR/.env${NC}"
    echo -e "   填完後：${CYAN}br service stop && br service start${NC}"
    echo ""
fi

echo -e "🚀 快速開始："
echo -e "   1. ${CYAN}source ~/.bashrc${NC}"
echo -e "   2. ${CYAN}br status${NC}"
echo -e "   3. ${CYAN}br index${NC}"
echo -e "   4. ${CYAN}br find <關鍵字>${NC}"
echo -e "   5. ${CYAN}br ask <問題>${NC}"
echo ""
echo -e "📖 完整說明：${CYAN}br help${NC}"
echo "========================================="
read -rp "✅ 安裝完成，按 Enter 關閉..."
exit 0
