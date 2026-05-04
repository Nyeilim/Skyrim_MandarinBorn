#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f set_env.sh ]; then source set_env.sh; fi

INDEXTTS_ROOT="$SCRIPT_DIR/index-tts"
cd "$INDEXTTS_ROOT"

echo "[INFO] 检查环境依赖..."
uv pip install pypinyin

echo "[INFO] 开始审计 Output_CN 目录..."
uv run "$SCRIPT_DIR/audit_english_files.py"

if [ $? -ne 0 ]; then
    echo "[ERROR] 审计脚本运行出错。"
    read -p "按回车键退出..."
    exit 1
fi

echo "[INFO] 审计清理完成！"
read -p "按回车键退出..."
