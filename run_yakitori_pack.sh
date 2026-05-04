#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f set_env.sh ]; then source set_env.sh; fi

echo "[INFO] 开始 FUZ 打包 (使用 FFmpeg + 纯 Python 实现)..."
echo "[INFO] 无需 xWMAEncode.exe 或 BmlFuzEncode.exe"

uv run "$SCRIPT_DIR/yakitori_pack.py"

if [ $? -ne 0 ]; then
    echo "[ERROR] 脚本运行出错。"
    read -p "按回车键退出..."
    exit 1
fi

echo "[INFO] 全部完成！压缩包已生成。"
read -p "按回车键退出..."
