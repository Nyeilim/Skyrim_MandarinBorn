#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f set_env.sh ]; then source set_env.sh; fi

INDEXTTS_ROOT="$SCRIPT_DIR/index-tts"
cd "$INDEXTTS_ROOT"

echo "[INFO] 开始读取 Whitelist.csv 并强制生成..."
uv run "$SCRIPT_DIR/tool_force_generate.py"

if [ $? -ne 0 ]; then
    echo "[ERROR] 脚本运行出错。"
    read -p "按回车键退出..."
    exit 1
fi

echo "[INFO] 白名单补全任务完成！"
read -p "按回车键退出..."
