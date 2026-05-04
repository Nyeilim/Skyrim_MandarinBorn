#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================================"
echo "        MandarinBorn (Linux) 一键安装脚本"
echo "======================================================================"
echo ""
echo "请选择您的网络环境 / Please select your network environment:"
echo ""
echo "[1] 中国大陆用户 (使用清华源加速 pip，使用 hf-mirror 加速模型下载)"
echo "[2] International Users (Use default official sources)"
echo ""
read -p "请输入数字 [1/2] (默认 1): " choice
choice=${choice:-1}

# 设置环境变量
if [ "$choice" = "1" ]; then
    export UV_INDEX_URL="https://pypi.tuna.tsinghua.edu.cn/simple"
    export HF_ENDPOINT="https://hf-mirror.com"
    export HF_MIRROR="https://hf-mirror.com"
    echo ""
    echo "[已启用] 国内加速模式"
    echo "- UV/Pip 源: 清华大学镜像"
    echo "- HF 源: hf-mirror.com"
else
    unset UV_INDEX_URL HF_ENDPOINT HF_MIRROR
    echo ""
    echo "[Enabled] International Mode"
fi

# 保存环境配置到 set_env.sh
if [ -n "$HF_ENDPOINT" ]; then
    cat > set_env.sh << ENVEOF
export HF_ENDPOINT="$HF_ENDPOINT"
export HF_MIRROR="$HF_MIRROR"
export UV_INDEX_URL="$UV_INDEX_URL"
ENVEOF
    echo "[成功] 已生成 set_env.sh"
else
    rm -f set_env.sh 2>/dev/null || true
fi

echo ""
echo "======================================================="
echo "0. 检查系统依赖..."
echo "======================================================="

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] 未找到 python3。请安装: sudo apt install python3 python3-venv"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "[INFO] Python 版本: $PYTHON_VERSION"

if python3 -c "import sys; exit(0 if (sys.version_info >= (3, 10) and sys.version_info < (3, 12)) else 1)"; then
    echo "[OK] Python 版本符合要求 (3.10 - 3.11)"
else
    echo "[ERROR] Python 版本需要 3.10 或 3.11，当前: $PYTHON_VERSION"
    exit 1
fi

# 检查系统工具
MISSING_TOOLS=()

if ! command -v ffmpeg &> /dev/null; then
    MISSING_TOOLS+=("ffmpeg")
fi

if ! command -v wine &> /dev/null; then
    echo "[WARNING] 未找到 wine。口型生成 (Runalip) 将被跳过。"
    echo "         安装: sudo apt install wine"
fi

if ! command -v 7z &> /dev/null; then
    echo "[WARNING] 未找到 7z。压缩打包将回退到 zip 格式。"
    echo "         安装: sudo apt install p7zip-full"
fi

if [ ${#MISSING_TOOLS[@]} -gt 0 ]; then
    echo "[ERROR] 缺少必要工具: ${MISSING_TOOLS[*]}"
    echo "安装命令: sudo apt install ${MISSING_TOOLS[*]}"
    read -p "是否现在安装？[y/n]: " install_choice
    if [ "$install_choice" = "y" ]; then
        sudo apt install -y ${MISSING_TOOLS[*]}
    else
        echo "请手动安装后重新运行此脚本。"
        exit 1
    fi
fi

echo ""
echo "======================================================="
echo "1. 检查并安装 uv 包管理器..."
echo "======================================================="
if command -v uv &> /dev/null; then
    echo "[INFO] uv 已安装，版本："
    uv --version
else
    echo "[INFO] 未检测到 uv，正在安装..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # 加载到当前 shell
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv &> /dev/null; then
        echo "[ERROR] uv 安装失败。请手动安装: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    echo "[成功] uv 已安装。"
fi

echo ""
echo "======================================================="
echo "2. 安装根目录依赖 (Whisper, Tools)..."
echo "======================================================="
echo "[INFO] 正在创建/同步根目录虚拟环境..."
uv sync
if [ $? -ne 0 ]; then
    echo "[ERROR] 根目录环境同步失败！"
    exit 1
fi

echo ""
echo "======================================================="
echo "3. 安装 IndexTTS 环境依赖 (TTS, PyTorch CUDA)..."
echo "-------------------------------------------------------"
echo "注意：PyTorch [CUDA版] 体积巨大，请耐心等待。"
echo "======================================================="
cd index-tts
echo "[INFO] 正在创建/同步 IndexTTS 虚拟环境..."
uv sync
if [ $? -ne 0 ]; then
    echo "[ERROR] IndexTTS 环境同步失败！"
    cd ..
    exit 1
fi
cd ..

echo ""
echo "======================================================="
echo "4. 复制共享数据 (从 Windows 版本)..."
echo "======================================================="
# 检查是否需要从 Windows 版本复制数据目录
WIN_PROJECT="D:/Softs/ImmersiveChineseVoice_ToolSet_v2.3"

# 这些目录包含游戏数据和模型文件，需要手动复制或链接
DATA_DIRS=(
    "Input"
    "Tools/Runalip"
    "index-tts/checkpoints"
)

MISSING_DATA=()
for dir in "${DATA_DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
        MISSING_DATA+=("$dir")
    fi
done

if [ ${#MISSING_DATA[@]} -gt 0 ]; then
    echo "[WARNING] 以下数据目录缺失 (需要从 Windows 版本复制):"
    for dir in "${MISSING_DATA[@]}"; do
        echo "  - $dir"
    done
    echo ""
    echo "请手动复制这些目录到此项目根目录:"
    echo "  cp -r <Windows版本路径>/$dir $SCRIPT_DIR/$dir"
    echo ""
    echo "或者创建符号链接:"
    echo "  ln -s <Windows版本路径>/$dir $SCRIPT_DIR/$dir"
fi

echo ""
echo "======================================================="
echo "所有安装步骤已完成！/ All Done!"
echo "======================================================="
echo ""
echo "使用方法:"
echo "  ./run_task.sh           - 生成中文语音 (主流程)"
echo "  ./run_generate_fx.sh    - 生成 FX 音效语音"
echo "  ./run_generate_dbvo.sh  - 生成 DBVO 语音"
echo "  ./run_yakitori_pack.sh  - 打包为 FUZ 格式"
echo "  ./run_scan_fx.sh        - 扫描 FX 音效"
echo ""
echo "注意事项:"
echo "  - 口型生成需要 wine (sudo apt install wine)"
echo "  - GPU 加速需要 NVIDIA 驱动和 CUDA"
echo ""
