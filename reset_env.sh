#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================="
echo "          MandarinBorn Linux 环境重置工具"
echo "======================================================="
echo ""
echo "[警告] 此操作将执行以下清理："
echo "1. 删除根目录虚拟环境 (.venv)"
echo "2. 删除 index-tts 虚拟环境 (index-tts/.venv)"
echo "3. 删除环境配置文件 (set_env.sh)"
echo "4. 清除所有 __pycache__ 缓存文件夹"
echo ""
read -p "确认要继续吗？[y/n]: " confirm
if [ "$confirm" != "y" ]; then exit 0; fi

echo ""
echo "[1/4] 正在删除根目录环境 (.venv)..."
if [ -d ".venv" ]; then
    rm -rf .venv
    echo "   已删除。"
else
    echo "   未找到，跳过。"
fi

echo ""
echo "[2/4] 正在删除 IndexTTS 环境 (index-tts/.venv)..."
if [ -d "index-tts/.venv" ]; then
    rm -rf index-tts/.venv
    echo "   已删除。"
else
    echo "   未找到，跳过。"
fi

echo ""
echo "[3/4] 正在删除配置文件 (set_env.sh)..."
if [ -f "set_env.sh" ]; then
    rm -f set_env.sh
    echo "   已删除。"
else
    echo "   未找到，跳过。"
fi

echo ""
echo "[4/4] 正在清理 __pycache__..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
echo "   已清理。"

echo ""
echo "======================================================="
echo "环境已重置。"
echo "现在您可以运行 ./install_linux.sh 进行重新安装。"
echo "======================================================="
