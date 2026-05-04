#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f set_env.sh ]; then source set_env.sh; fi

if [ $# -eq 0 ]; then
    echo "用法: 将 .fuz 文件路径作为参数传入"
    echo "  ./fuz_to_wav.sh file1.fuz file2.fuz ..."
    read -p "按回车键退出..."
    exit 1
fi

uv run python tool_fuz_to_wav.py "$@"

if [ $? -ne 0 ]; then
    echo "[ERROR] 运行出错。"
else
    echo "[SUCCESS] 运行结束。"
fi

read -p "按回车键退出..."
