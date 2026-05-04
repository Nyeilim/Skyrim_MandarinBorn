#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ -f set_env.sh ]; then source set_env.sh; fi

INDEXTTS_ROOT="$SCRIPT_DIR/index-tts"
cd "$INDEXTTS_ROOT"

echo "[INFO] 开始生成 FX 中文语音..."
uv run "$SCRIPT_DIR/generate_fx_voice.py"

if [ $? -ne 0 ]; then
    echo "[ERROR] 生成过程中出错。"
    read -p "按回车键退出..."
    exit 1
fi

echo "[INFO] 所有任务完成！"
read -p "按回车键退出..."
