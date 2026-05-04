import os
import sys
import csv
import subprocess
import shutil
import logging
from pathlib import Path

# ================= 配置区域 =================
PROJECT_ROOT = Path(__file__).parent.absolute()
# FFmpeg 路径
FFMPEG_EXE = PROJECT_ROOT / "ffmpeg/bin/ffmpeg"
# IndexTTS 路径
INDEXTTS_DIR = PROJECT_ROOT / "index-tts"

# 输入输出
INPUT_ROOT = PROJECT_ROOT / "Input"
CSV_FILE = INPUT_ROOT / "Fx_Transcriptions.csv"
OUTPUT_DIR = PROJECT_ROOT / "Output_CN"
TEMP_DIR = PROJECT_ROOT / "temp_fx_processing"

# IndexTTS 配置
INDEXTTS_CHECKPOINTS = INDEXTTS_DIR / "checkpoints"
INDEXTTS_CONFIG = INDEXTTS_CHECKPOINTS / "config.yaml"

# 记录混合文本日志
MIXED_LOG_FILE = PROJECT_ROOT / "manual_fix_required.txt"

# ===========================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_environment():
    if str(FFMPEG_EXE) != "ffmpeg" and not FFMPEG_EXE.exists():
        logger.error(f"找不到 FFmpeg: {FFMPEG_EXE}")
        sys.exit(1)

    if not INDEXTTS_DIR.exists():
        logger.error(f"找不到 IndexTTS 目录: {INDEXTTS_DIR}")
        sys.exit(1)

    # 动态添加 IndexTTS 到 Python 路径
    if str(INDEXTTS_DIR) not in sys.path:
        sys.path.insert(0, str(INDEXTTS_DIR))

    OUTPUT_DIR.mkdir(exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)

def convert_audio_to_wav(source_path, output_wav_path):
    """将源音频转为 44.1k wav 作为 prompt"""
    cmd = [
        str(FFMPEG_EXE),
        '-y', '-v', 'error',
        '-i', str(source_path),
        '-ac', '1',
        '-ar', '44100',
        '-c:a', 'pcm_s16le',
        str(output_wav_path)
    ]
    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError:
        logger.error(f"转换音频失败: {source_path}")
        return False

def init_indextts():
    """初始化 IndexTTS 模型"""
    logger.info("正在加载 IndexTTS 模型...")
    original_cwd = os.getcwd()
    os.chdir(INDEXTTS_DIR)

    try:
        from indextts.infer_v2 import IndexTTS2
        tts = IndexTTS2(
            cfg_path=str(INDEXTTS_CONFIG),
            model_dir=str(INDEXTTS_CHECKPOINTS),
            use_fp16=False,
            use_cuda_kernel=False,
            use_deepspeed=False
        )
    except ImportError as e:
        logger.error("无法导入 IndexTTS 模块，请检查依赖")
        raise e
    finally:
        os.chdir(original_cwd)
    return tts

def main():
    setup_environment()

    if not CSV_FILE.exists():
        logger.error(f"找不到 CSV 文件: {CSV_FILE}")
        logger.info("请先运行 tool_scan_fx_whisper.py 生成 CSV。")
        return

    # 1. 预读 CSV
    rows_to_process = []
    try:
        with open(CSV_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('TranslatedText') and row.get('TranslatedText').strip():
                    rows_to_process.append(row)
    except Exception as e:
        logger.error(f"读取 CSV 失败: {e}")
        return

    if not rows_to_process:
        logger.info("没有发现包含 'TranslatedText' 的有效条目。")
        logger.info("请打开 Input/Fx_Transcriptions.csv 并填入中文翻译。")
        return

    # 2. 初始化模型
    try:
        tts_model = init_indextts()
    except Exception as e:
        logger.error(f"模型加载失败: {e}")
        return

    logger.info(f"开始处理 {len(rows_to_process)} 个文件...")
    success_count = 0
    mixed_logs = []

    # 3. 循环处理
    for i, row in enumerate(rows_to_process):
        rel_path_str = row.get('RelativePath', '')
        file_name = row.get('FileName', '')
        chinese_text = row.get('TranslatedText', '').strip()
        orig_text = row.get('OriginalText', '')

        if not rel_path_str:
            continue

        if '*' in orig_text or '(' in orig_text or '[' in orig_text:
            log_entry = f"FX | {file_name} | {orig_text}"
            mixed_logs.append(log_entry)

        # 修正路径分隔符
        rel_path = Path(rel_path_str.replace('\\', '/'))

        output_rel_path = rel_path
        if rel_path.parts[0].lower() == 'skyrimvoice':
            output_rel_path = Path(*rel_path.parts[1:])

        src_path = INPUT_ROOT / rel_path

        if not src_path.exists():
            logger.warning(f"[{i+1}] 源文件缺失: {src_path}")
            continue

        target_file_path = OUTPUT_DIR / output_rel_path.with_suffix('.wav')
        target_file_path.parent.mkdir(parents=True, exist_ok=True)

        temp_prompt = TEMP_DIR / f"prompt_{i}_{file_name}.wav"

        try:
            if not convert_audio_to_wav(src_path, temp_prompt):
                continue

            logger.info(f"[{i+1}/{len(rows_to_process)}] 生成: {file_name} -> {chinese_text}")

            original_cwd = os.getcwd()
            os.chdir(INDEXTTS_DIR)

            try:
                tts_model.infer(
                    spk_audio_prompt=str(temp_prompt),
                    text=chinese_text,
                    output_path=str(target_file_path),
                    use_random=False,
                    verbose=False
                )
                success_count += 1
            except Exception as e:
                logger.error(f"  生成出错: {e}")
            finally:
                os.chdir(original_cwd)

        except Exception as e:
            logger.error(f"  处理异常: {e}")
        finally:
            if temp_prompt.exists():
                try: os.remove(temp_prompt)
                except: pass

    # 清理临时目录
    try: shutil.rmtree(TEMP_DIR)
    except: pass

    # 写入混合文本日志
    if mixed_logs:
        with open(MIXED_LOG_FILE, 'a', encoding='utf-8') as f:
            f.write("\n=== FX Mixed Audio Logs ===\n")
            f.write("\n".join(mixed_logs))
            f.write("\n")
        logger.info(f"已记录 {len(mixed_logs)} 条混合音频需人工修复，查看: {MIXED_LOG_FILE}")

    logger.info(f"处理完成！成功生成: {success_count}/{len(rows_to_process)}")
    if success_count > 0:
        logger.info(f"文件已保存至: {OUTPUT_DIR}")

if __name__ == "__main__":
    main()
