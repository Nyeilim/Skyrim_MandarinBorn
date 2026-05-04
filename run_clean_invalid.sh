#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f set_env.sh ]; then source set_env.sh; fi

echo "[INFO] 开始执行无效文件清理..."
uv run "$SCRIPT_DIR/Tools/clean_invalid_files.py"

if [ $? -ne 0 ]; then
    echo "[ERROR] 脚本运行出错。"
    read -p "按回车键退出..."
    exit 1
fi

echo "[INFO] 清理任务完成！"
read -p "按回车键退出..."
