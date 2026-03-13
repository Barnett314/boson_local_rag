#!/bin/bash
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"
source .venv/bin/activate
echo "$(date) === 索引更新 ===" >> logs/daily_update.log
python build_index.py >> logs/daily_update.log 2>&1
curl -s "http://127.0.0.1:8900/cache/clear"
