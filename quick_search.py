#!/usr/bin/env python3
"""
快速搜尋腳本：結合 grep + Boson RAG 向量搜尋
跳過複雜的語義索引，直接使用最有效的方法
"""

import os
import subprocess
import sys
from pathlib import Path

# 動態獲取專案路徑
PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

# 從 config 自動匯入 VAULT_PATH
try:
    from config import VAULT_PATH
except ImportError:
    VAULT_PATH = os.getenv("VAULT_PATH", str(Path.home() / "Documents/KnowledgeBase"))

def grep_search(query):
    """傳統 grep 搜尋 - 最可靠"""
    print(f"🔍 傳統搜尋: {query}")
    cmd = f"grep -r -l '{query}' '{VAULT_PATH}' --include='*.md' 2>/dev/null | head -10"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    files = []
    for line in result.stdout.strip().split('\n'):
        if line:
            files.append(line)
    
    return files

def boson_search(query):
    """Boson RAG 向量搜尋 - 語義理解"""
    print(f"🤖 Boson 向量搜尋: {query}")
    try:
        # 使用動態路徑執行 query.py 進行搜尋
        cmd = f"cd '{PROJECT_DIR}' && source .venv/bin/activate && python boson_query.py '{query}' --mode search"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        
        # 解析結果
        lines = result.stdout.strip().split('\n')
        files = []
        for line in lines:
            if line.startswith('📄'):
                # 格式: 📄 檔案名.md (相似度 0.xx)
                parts = line.split(' (相似度')
                if parts:
                    filename = parts[0].replace('📄 ', '').strip()
                    files.append(filename)
        
        return files[:5]  # 取前5個
    except Exception as e:
        print(f"⚠️ Boson 搜尋失敗: {e}")
        return []

def hybrid_search(query):
    """混合搜尋策略"""
    print(f"🎯 混合搜尋: {query}")
    
    # 1. 先試傳統搜尋 (最快)
    grep_results = grep_search(query)
    if grep_results:
        print(f"✅ 傳統搜尋找到 {len(grep_results)} 個檔案")
        for f in grep_results[:3]:
            try:
                # 嘗試只顯示相對路徑，讓版面更乾淨
                rel_path = Path(f).relative_to(VAULT_PATH)
                print(f"   - {rel_path}")
            except ValueError:
                print(f"   - {f}")
    
    # 2. 再試 Boson 搜尋 (語義理解)
    boson_results = boson_search(query)
    if boson_results:
        print(f"✅ Boson 搜尋找到 {len(boson_results)} 個檔案")
        for f in boson_results[:3]:
            print(f"   - {f}")
    
    # 3. 合併結果
    all_results = list(set(grep_results + boson_results))
    
    if not all_results:
        print("❌ 沒有找到相關檔案")
    
    return all_results

def main():
    if len(sys.argv) < 2:
        print("使用方法: python quick_search.py <查詢詞>")
        sys.exit(1)
    
    query = sys.argv[1]
    print(f"\n=== 搜尋: {query} ===\n")
    
    results = hybrid_search(query)
    
    print(f"\n=== 總計找到 {len(results)} 個檔案 ===")

if __name__ == "__main__":
    main()
