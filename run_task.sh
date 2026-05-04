#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 加载环境配置 (用于国内加速)
if [ -f set_env.sh ]; then
    source set_env.sh
fi

INDEXTTS_ROOT="$SCRIPT_DIR/index-tts"

echo "[INFO] 正在初始化运行环境..."
echo "[INFO] 开始执行语音生成任务..."
echo "[INFO] 请耐心等待模型加载..."

# 确保依赖已安装
cd "$INDEXTTS_ROOT"
uv pip install pypinyin

# 运行脚本
"$INDEXTTS_ROOT/.venv/bin/python" "$SCRIPT_DIR/generate_voice.py"

if [ $? -ne 0 ]; then
    echo "[ERROR] 脚本运行出错，错误代码: $?"
    read -p "按回车键退出..."
    exit 1
fi

echo "[INFO] 任务完成！"
read -p "按回车键退出..."
