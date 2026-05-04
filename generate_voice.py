import os
import sys
import csv
import subprocess
import shutil
import logging
import re
import struct
from pathlib import Path
from pypinyin import pinyin, Style
from filter_logic import should_skip_voice
from whitelist_logic import is_in_whitelist

# ================= 配置区域 =================

# 1. 路径配置 (动态获取)
PROJECT_ROOT = Path(__file__).resolve().parent

# FFmpeg 路径策略: 优先使用项目内置的 ffmpeg 文件夹，否则尝试系统 PATH
FFMPEG_LOCAL = PROJECT_ROOT / "ffmpeg/bin/ffmpeg"
FFPROBE_LOCAL = PROJECT_ROOT / "ffmpeg/bin/ffprobe"

# Runalip 路径 (必须在项目内，通过 wine 调用)
RUNALIP_EXE = PROJECT_ROOT / "Tools/Runalip/Runalip.exe"
USE_WINE_FOR_RUNALIP = True  # Linux 上通过 wine 运行 Runalip

# 动态查找 FFmpeg
if FFMPEG_LOCAL.exists():
    FFMPEG_EXE = FFMPEG_LOCAL
    FFPROBE_EXE = FFPROBE_LOCAL
else:
    # 尝试直接调用命令 (假设在 PATH 中)
    FFMPEG_EXE = Path("ffmpeg")
    FFPROBE_EXE = Path("ffprobe")

INDEXTTS_DIR = PROJECT_ROOT / "index-tts"

# 2. 输入输出配置
# 修改为指向 SkyrimVoice 的 voice 根目录，包含所有插件文件夹
SOURCE_VOICE_ROOT = PROJECT_ROOT / "Input/SkyrimVoice/sound/voice"
CSV_FILE = PROJECT_ROOT / "Input/LazyVoiceFinder_export.csv"
OUTPUT_DIR = PROJECT_ROOT / "Output_CN"
TEMP_DIR = PROJECT_ROOT / "temp_processing"

# 记录需要人工修复的文件列表 (混合音频)
MIXED_LOG_FILE = PROJECT_ROOT / "manual_fix_required.txt"

# 3. IndexTTS 配置 (相对于 INDEXTTS_DIR)
INDEXTTS_CHECKPOINTS = INDEXTTS_DIR / "checkpoints"
INDEXTTS_CONFIG = INDEXTTS_CHECKPOINTS / "config.yaml"

# 4. 语音生成配置
GLOBAL_SPEED = 1.0

# ===========================================

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_environment():
    """将 IndexTTS 添加到系统路径并验证工具"""

    # ffmpeg: 如果是 Path 对象且指向本地文件，检查是否存在；如果是 "ffmpeg" 命令，用 which 检查
    if str(FFMPEG_EXE) != "ffmpeg" and not FFMPEG_EXE.exists():
        logger.error(f"找不到 FFmpeg: {FFMPEG_EXE}")
        sys.exit(1)

    if USE_WINE_FOR_RUNALIP and not shutil.which("wine"):
        logger.warning("未检测到 wine，将跳过口型生成步骤。安装 wine: sudo apt install wine")
        global USE_WINE_FOR_RUNALIP
        USE_WINE_FOR_RUNALIP = False

    if not RUNALIP_EXE.exists():
        logger.warning(f"找不到 Runalip: {RUNALIP_EXE}，将跳过口型生成步骤。")

    if not INDEXTTS_DIR.exists():
        logger.error(f"找不到 IndexTTS 目录: {INDEXTTS_DIR}")
        sys.exit(1)

    # 动态添加 IndexTTS 到 Python 路径
    # 这一步对于在 uv 环境下运行也是必要的，因为 indextts 包在 index-tts 根目录下
    if str(INDEXTTS_DIR) not in sys.path:
        sys.path.insert(0, str(INDEXTTS_DIR))

    # 创建输出目录
    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)

    # 创建 debug 目录存放参考音频副本
    (OUTPUT_DIR / "_debug_ref_wavs").mkdir(exist_ok=True)

def get_audio_duration(file_path):
    """使用 FFprobe 获取音频时长 (秒)"""
    try:
        cmd = [
            str(FFPROBE_EXE),
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path)
        ]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True)
        return float(result.stdout.strip())
    except Exception as e:
        logger.warning(f"无法获取音频时长 {file_path}: {e}")
        return None

def calculate_dynamic_speed(text, original_duration):
    """
    计算推荐的语速 (Speed)。

    策略：[自然语速优先，不强制匹配时长]
    1. 估算中文自然朗读时长 (Natural Duration)。
    2. 计算为了完全匹配所需的"强制语速" (Required Speed)。
    3. 设定"自然语速舒适区" (0.9 ~ 1.15)：
       - 只要原来的音频时长导致的计算语速在这个范围内，我们就微调语速去匹配原时长（为了更好的口型同步）。
       - 如果计算出的语速超出这个范围（比如原文极长或极短），我们**不再强行匹配**，而是直接使用自然语速（1.0）或者只进行微小的边界调整。
       - 放弃静音填充：游戏引擎通常能处理不同时长的语音，优先保证语音本身的自然听感。

    返回: speed
    """
    if not original_duration or original_duration <= 0:
        return 1.0

    # 1. 估算中文自然时长
    clean_text = re.sub(r'[^\w\s]', '', text)
    char_count = len(clean_text)
    punct_count = len(text) - char_count

    # 估算公式
    # 汉字: ~0.24s (IndexTTS2 咬字清晰)
    # 标点: ~0.15s
    # 基础缓冲: 0.3s
    natural_duration = (char_count * 0.24) + (punct_count * 0.15) + 0.3

    # 2. 计算完全匹配所需的语速
    required_speed = natural_duration / original_duration

    # 3. 动态调整策略
    if 0.9 <= required_speed <= 1.15:
        return required_speed

    if required_speed < 0.9:
        return 0.95

    if required_speed > 1.15:
        return 1.1

    return 1.0

def build_file_index(source_root):
    """遍历源文件夹建立文件名索引，支持多层级查找"""
    logger.info(f"正在建立源文件索引: {source_root} ...")
    file_index = {}
    # 支持的源音频格式
    valid_exts = {'.xwm', '.wav', '.fuz', '.wmv', '.mp3'}

    for root, _, files in os.walk(source_root):
        for file in files:
            path = Path(root) / file
            if path.suffix.lower() in valid_exts:
                # 存储: {文件名(无后缀): [完整路径1, 完整路径2, ...]}
                # 支持同名文件存在于不同目录
                stem = path.stem.lower()
                if stem not in file_index:
                    file_index[stem] = []
                file_index[stem].append(path)

    logger.info(f"索引建立完成，共找到 {len(file_index)} 个唯一文件名。")
    return file_index

def extract_fuz_audio(fuz_path, output_xwm_path):
    """从 FUZ 文件中提取 XWM 音频"""
    try:
        with open(fuz_path, 'rb') as f:
            header = f.read(4)
            if header != b'FUZE':
                return False

            # Skip Version (4 bytes)
            f.read(4)

            # Read Lip Size (4 bytes)
            lip_size_bytes = f.read(4)
            if len(lip_size_bytes) < 4:
                return False
            lip_size = struct.unpack('I', lip_size_bytes)[0]

            # Skip Lip Data
            f.seek(lip_size, 1)

            # The rest is Audio Data (usually XWM)
            audio_data = f.read()

            if not audio_data:
                return False

            with open(output_xwm_path, 'wb') as out_f:
                out_f.write(audio_data)

            return True
    except Exception as e:
        logger.error(f"解包 FUZ 失败 {fuz_path}: {e}")
        return False

def convert_audio_to_wav(source_path, output_wav_path):
    """使用 FFmpeg 将任意音频转换为 44.1k mono wav (保留高频细节作为 Prompt)"""

    temp_xwm = None
    input_path = source_path

    # 处理 .fuz 文件：先提取音频部分
    if source_path.suffix.lower() == '.fuz':
        temp_xwm = TEMP_DIR / (source_path.stem + f"_temp_{os.getpid()}.xwm")

        if extract_fuz_audio(source_path, temp_xwm):
            input_path = temp_xwm
        else:
            logger.warning(f"无法从 FUZ 提取音频，尝试直接转换: {source_path}")

    cmd = [
        str(FFMPEG_EXE),
        '-y',  # 覆盖输出
        '-i', str(input_path),
        '-ac', '1',      # 单声道
        '-ar', '44100',
        '-c:a', 'pcm_s16le',
        str(output_wav_path),
        '-loglevel', 'error'
    ]

    try:
        subprocess.run(cmd, check=True)
    finally:
        # 清理临时解包的文件
        if temp_xwm and temp_xwm.exists():
            try:
                os.remove(temp_xwm)
            except:
                pass

def get_pinyin_text(chinese_text):
    """将中文转换为不带声调的拼音 (Runalip/FaceFX 格式)，并去除标点"""
    # Style.NORMAL 生成不带声调的拼音 (如 ni hao)
    result = pinyin(chinese_text, style=Style.NORMAL, heteronym=False)

    # 展平列表
    pinyin_list = [item[0] for item in result]
    pinyin_str = " ".join(pinyin_list)

    # 关键修正：去除所有非字母数字和空格的字符（即去除标点符号）
    # FaceFX 不需要标点，且 CSV 中的逗号可能导致解析错误
    clean_pinyin = re.sub(r'[^\w\s]', '', pinyin_str).strip()

    return clean_pinyin

def init_indextts():
    """初始化 IndexTTS 模型"""
    logger.info("正在加载 IndexTTS 模型 (这可能需要一点时间)...")

    # 切换工作目录到 IndexTTS 文件夹，防止相对路径报错
    original_cwd = os.getcwd()
    os.chdir(INDEXTTS_DIR)

    try:
        from indextts.infer_v2 import IndexTTS2
        # 初始化模型
        tts = IndexTTS2(
            cfg_path=str(INDEXTTS_CONFIG),
            model_dir=str(INDEXTTS_CHECKPOINTS),
            use_fp16=False,
            use_cuda_kernel=False,
            use_deepspeed=False
        )
    except ImportError as e:
        logger.error("无法导入 IndexTTS 模块，请检查路径设置。")
        raise e
    finally:
        # 恢复工作目录
        os.chdir(original_cwd)

    return tts

def main():
    setup_environment()

    # 1. 初始化 TTS 模型
    try:
        tts_model = init_indextts()
    except Exception as e:
        logger.error(f"模型加载失败: {e}")
        return

    # 2. 建立文件索引
    file_map = build_file_index(SOURCE_VOICE_ROOT)

    # 3. 准备 Runalip 的 CSV 数据列表
    # Runalip 需要的列: State, Plugin, File Name, Voice Type, Dialogue 1, Dialogue 2
    runalip_rows = []
    mixed_audio_logs = [] # 记录混合音频

    # 4. 读取原始 CSV 并处理
    logger.info("开始处理 CSV...")
    success_count = 0
    skip_count = 0

    with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        for i, row in enumerate(reader):
            file_name_raw = row.get('File Name', '').strip()
            # Dialogue 1 - English 是原本的中文文本列
            raw_text = row.get('Dialogue 1 - English', '').strip()

            if not file_name_raw or not raw_text:
                continue

            # 显式检查 State 列，跳过无效条目
            state_val = row.get('State', '').lower()
            if 'bad file' in state_val or 'no voice' in state_val:
                skip_count += 1
                continue

            # 使用统一过滤逻辑
            should_skip, skip_reason, chinese_text = should_skip_voice(
                file_name_raw,
                raw_text,
                row.get('Voice Type', ''),
                row.get('Dialogue 2', '')
            )

            if should_skip:
                # 检查白名单 (传入 Plugin)
                current_plugin = row.get('Plugin', 'skyrim.esm')
                if is_in_whitelist(file_name_raw, row.get('Voice Type', ''), current_plugin):
                    logger.info(f"白名单命中，强制保留: {file_name_raw} [{current_plugin}]")
                    should_skip = False
                else:
                    skip_count += 1
                    continue

            # 获取不带后缀的文件名用于查找
            stem_name = Path(file_name_raw).stem.lower()

            # A. 查找源文件
            possible_paths = file_map.get(stem_name, [])
            if not possible_paths:
                skip_count += 1
                continue

            # 尝试根据 Plugin 和 Voice Type 精确匹配源文件
            csv_plugin = row.get('Plugin', '').strip().lower()
            csv_voice_type = row.get('Voice Type', '').strip().lower()
            src_file_path = None

            # 策略1: 精确匹配 (Plugin 和 VoiceType 都匹配)
            for path in possible_paths:
                try:
                    rel_parts = path.relative_to(SOURCE_VOICE_ROOT).parts
                    if len(rel_parts) >= 2:
                        path_plugin = rel_parts[0].lower()
                        path_voice_type = rel_parts[1].lower()

                        if path_plugin == csv_plugin and path_voice_type == csv_voice_type:
                            src_file_path = path
                            break
                except ValueError:
                    continue

            # 策略2: 如果只有一个候选文件，直接使用 (容错)
            if not src_file_path and len(possible_paths) == 1:
                src_file_path = possible_paths[0]

            # 策略3: 如果有多个候选但没匹配上，尝试只匹配 VoiceType (容错 Plugin 命名不一致)
            if not src_file_path:
                for path in possible_paths:
                    if path.parent.name.lower() == csv_voice_type:
                        src_file_path = path
                        break

            if not src_file_path:
                logger.warning(f"无法定位唯一源文件: {file_name_raw} (候选数: {len(possible_paths)}, 需匹配: {csv_plugin}/{csv_voice_type})")
                skip_count += 1
                continue

            # B. 确定输出路径 (保持目录结构)
            try:
                rel_path = src_file_path.relative_to(SOURCE_VOICE_ROOT).parent
            except ValueError:
                rel_path = Path(".")

            # 最终的目标文件夹: Output_CN / sound / voice / ...
            target_folder = OUTPUT_DIR / "sound" / "voice" / rel_path
            target_folder.mkdir(parents=True, exist_ok=True)

            # 目标音频文件名 (.wav)
            target_wav_name = Path(file_name_raw).with_suffix('.wav').name
            target_wav_path = target_folder / target_wav_name

            if (i + 1) % 100 == 0:
                logger.info(f"进度: 已处理 {i+1} 行...")

            try:
                # 如果是混合文本，记录到日志
                if raw_text != chinese_text:
                        mixed_audio_logs.append(f"{file_name_raw} | {raw_text}")

                # C. 转换参考音频 (Temp)
                # 如果目标文件已存在，跳过生成，但仍加入 Runalip 列表
                if target_wav_path.exists():
                    pass
                else:
                    # 使用唯一文件名: ref_Plugin_VoiceType_FileName.wav
                    ref_audio_filename = f"ref_{src_file_path.parent.parent.name}_{src_file_path.parent.name}_{stem_name}.wav"
                    ref_audio_path = TEMP_DIR / ref_audio_filename

                    convert_audio_to_wav(src_file_path, ref_audio_path)

                    # D. 调用 IndexTTS 生成中文音频
                    original_cwd = os.getcwd()
                    os.chdir(INDEXTTS_DIR)

                    prompt_path_abs = os.path.abspath(str(ref_audio_path))
                    output_path_abs = os.path.abspath(str(target_wav_path))

                    # 计算动态语速
                    orig_duration = get_audio_duration(prompt_path_abs)
                    dynamic_speed = calculate_dynamic_speed(chinese_text, orig_duration)

                    # 捕获可能的异常，防止一个失败卡死整个流程
                    try:
                        tts_model.infer(
                            spk_audio_prompt=prompt_path_abs,
                            text=chinese_text,
                            output_path=output_path_abs,
                            use_random=False,
                            verbose=False,
                            speed=dynamic_speed
                        )
                        logger.info(f"[{success_count+1}] 生成: {file_name_raw} (Spd: {dynamic_speed:.2f})")

                    except Exception as tts_err:
                        logger.error(f"TTS生成失败 {file_name_raw}: {tts_err}")
                        # 复制原声兜底
                        shutil.copy2(prompt_path_abs, output_path_abs)

                    os.chdir(original_cwd)

                    # 清理本次使用的临时参考文件
                    try:
                        os.remove(ref_audio_path)
                    except Exception:
                        pass

                pinyin_text = get_pinyin_text(chinese_text)
                clean_chinese_text = ""

                # E. 准备 Runalip 数据
                new_row = {
                    "State": "",
                    "Plugin": row.get('Plugin', 'skyrim.esm'),
                    "File Name": target_wav_name,
                    "Voice Type": row.get('Voice Type', 'None'),
                    "Dialogue 1": clean_chinese_text,
                    "Dialogue 2": pinyin_text
                }
                runalip_rows.append(new_row)

                success_count += 1

            except Exception as e:
                logger.error(f"处理失败 {file_name_raw}: {e}")
                os.chdir(PROJECT_ROOT)

    logger.info(f"语音合成完成。成功: {success_count}, 跳过/失败: {skip_count}")

    # 写入人工修复清单
    if mixed_audio_logs:
        with open(MIXED_LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("File Name | Original Text (Contains SFX)\n")
            f.write("----------------------------------------\n")
            f.write("\n".join(mixed_audio_logs))
        logger.info(f"已生成混合音频人工修复清单: {MIXED_LOG_FILE}")

    # 5. 生成 Runalip 专用 CSV
    if not runalip_rows:
        logger.error("没有生成任何文件，跳过 Runalip 步骤。")
        return

    runalip_csv_path = OUTPUT_DIR / "runalip_list.csv"
    logger.info(f"正在生成 Runalip 列表: {runalip_csv_path}")

    csv_headers = ["State", "Plugin", "File Name", "Voice Type", "Dialogue 1", "Dialogue 2"]
    with open(runalip_csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers, lineterminator='\r\n')
        writer.writeheader()
        writer.writerows(runalip_rows)

    # 6. 调用 Runalip 生成 Lip 文件
    if not USE_WINE_FOR_RUNALIP or not RUNALIP_EXE.exists():
        logger.warning("跳过口型生成 (Runalip 不可用)。")
        logger.warning("如需口型文件，请安装 wine 并确保 Tools/Runalip/Runalip.exe 存在。")
    else:
        logger.info("正在通过 Wine 调用 Runalip 生成口型文件...")

        # 创建一个临时的 Lip 生成目录，避免 Runalip 自我复制冲突
        lip_gen_dir = PROJECT_ROOT / "Temp_Lip_Output"
        if lip_gen_dir.exists():
            shutil.rmtree(lip_gen_dir)
        lip_gen_dir.mkdir(exist_ok=True)

        # Runalip -genlips [Game] [FileBaseCSV] [SrcPath] [DstPath]
        runalip_cmd = [
            "wine", str(RUNALIP_EXE),
            "-genlips",
            "SSE",
            str(runalip_csv_path),
            str(OUTPUT_DIR / "sound" / "voice"),
            str(lip_gen_dir)
        ]

        try:
            process = subprocess.Popen(
                runalip_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding='utf-8',
                cwd=OUTPUT_DIR
            )

            # 实时打印 Runalip 输出，但限制行数防止刷屏
            line_count = 0
            for line in process.stdout:
                line_count += 1
                if line_count < 20 or line_count % 100 == 0:
                    print(f"[Runalip] {line.strip()}")

            process.wait()
            logger.info("Runalip 流程结束。")

            # 7. 将生成的 Lip 文件移回 Output_CN
            logger.info("正在将 Lip 文件移回输出目录...")
            move_count = 0
            for lip_file in lip_gen_dir.rglob("*.lip"):
                rel_path = lip_file.relative_to(lip_gen_dir)
                target_lip_path = OUTPUT_DIR / "sound" / "voice" / rel_path
                target_lip_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(lip_file), str(target_lip_path))
                move_count += 1

            logger.info(f"成功移动了 {move_count} 个 Lip 文件。")

            # 清理 Lip 临时目录
            shutil.rmtree(lip_gen_dir)

        except Exception as e:
            logger.error(f"Runalip 调用或处理失败: {e}")

    # 清理临时文件
    try:
        shutil.rmtree(TEMP_DIR)
    except:
        pass

    logger.info("全部任务完成！")

if __name__ == "__main__":
    main()
