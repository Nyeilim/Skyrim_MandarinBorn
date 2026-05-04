#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f set_env.sh ]; then source set_env.sh; fi

echo "[INFO] 正在启动 FX 音频扫描工具..."

uv run tool_scan_fx_whisper.py "$@"

if [ $? -ne 0 ]; then
    echo "[ERROR] 扫描过程中出错。"
    read -p "按回车键退出..."
    exit 1
fi

echo "[INFO] 扫描完成！请检查 Input/Fx_Transcriptions.csv"
read -p "按回车键退出..."
