import os
import struct
import subprocess
import logging
import shutil
import concurrent.futures
from pathlib import Path

# 配置
PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "Output_CN"
SOURCE_SOUND_DIR = OUTPUT_DIR / "sound"
COMPRESSED_DIR = OUTPUT_DIR / "Compressed"
TARGET_SOUND_DIR = COMPRESSED_DIR / "sound"
FINAL_ARCHIVE = OUTPUT_DIR / "ImmersiveChineseVoicePack_Final.7z"

# 7-Zip: Linux 上直接用系统 7z
SEVEN_ZIP_EXE = shutil.which("7z") or shutil.which("7za")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def compress_folder(source_dir, output_archive):
    logger.info(f"正在压缩文件夹: {source_dir} -> {output_archive}")

    if SEVEN_ZIP_EXE:
        cmd = [
            SEVEN_ZIP_EXE, 'a', '-t7z', '-mx=9',
            str(output_archive),
            str(source_dir) + "/*"
        ]
        subprocess.run(cmd, check=True)
    else:
        archive_name = str(Path(output_archive).with_suffix(''))
        shutil.make_archive(archive_name, 'zip', source_dir)
        if output_archive.endswith('.7z'):
             logger.warning("找不到 7-Zip，已回退到 .zip 格式。安装: sudo apt install p7zip-full")

def wav_to_xwm_ffmpeg(wav_path, xwm_path):
    """使用 FFmpeg 将 WAV 编码为 WMA (XWM 兼容格式)"""
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(wav_path),
        "-c:a", "wmav2", "-b:a", "48k",
        str(xwm_path)
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False

def create_fuz(fuz_path, xwm_path, lip_path):
    """纯 Python 实现 FUZ 打包 (替代 BmlFuzEncode.exe)"""
    try:
        # 读取 XWM/WMA 音频数据
        with open(xwm_path, 'rb') as f:
            audio_data = f.read()

        # 读取 LIP 数据 (如果存在)
        lip_data = b''
        if lip_path and lip_path.exists():
            with open(lip_path, 'rb') as f:
                lip_data = f.read()

        # FUZ 格式: 'FUZE' + Version(4) + LipSize(4) + LipData + AudioData
        with open(fuz_path, 'wb') as f:
            f.write(b'FUZE')
            f.write(struct.pack('<I', 1))  # Version
            f.write(struct.pack('<I', len(lip_data)))
            f.write(lip_data)
            f.write(audio_data)

        return True
    except Exception as e:
        logger.error(f"FUZ 打包失败: {e}")
        return False

def process_single_file(wav_path, fuz_path, lip_path):
    """处理单个文件：WAV -> WMA -> FUZ (纯跨平台实现)"""
    temp_xwm = wav_path.with_suffix('.wma')

    try:
        # 1. WAV -> WMA (使用 FFmpeg wmav2 编码)
        if not wav_to_xwm_ffmpeg(wav_path, temp_xwm):
            logger.error(f"WMA 转换失败: {wav_path}")
            return False

        if not temp_xwm.exists():
            logger.error(f"WMA 文件未生成: {wav_path}")
            return False

        # 2. WMA + LIP -> FUZ (纯 Python 打包)
        return create_fuz(fuz_path, temp_xwm, lip_path)

    except Exception as e:
        logger.error(f"处理失败 {wav_path.name}: {e}")
        return False
    finally:
        if temp_xwm.exists():
            try: os.remove(temp_xwm)
            except: pass

def main():
    if not OUTPUT_DIR.exists():
        logger.error(f"找不到输出目录: {OUTPUT_DIR}")
        return

    # 准备输出目录
    if COMPRESSED_DIR.exists():
        shutil.rmtree(COMPRESSED_DIR)
    COMPRESSED_DIR.mkdir(parents=True, exist_ok=True)
    TARGET_SOUND_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("开始批量转换 (WAV -> FUZ)...")

    tasks = []
    for root, _, files in os.walk(SOURCE_SOUND_DIR):
        for file in files:
            if file.lower().endswith('.wav'):
                wav_path = Path(root) / file

                rel_path = wav_path.relative_to(OUTPUT_DIR)
                target_fuz_path = COMPRESSED_DIR / rel_path.with_suffix('.fuz')
                target_fuz_path.parent.mkdir(parents=True, exist_ok=True)

                lip_path = wav_path.with_suffix('.lip')

                tasks.append((wav_path, target_fuz_path, lip_path))

    total_files = len(tasks)
    max_workers = os.cpu_count() or 4
    logger.info(f"找到 {total_files} 个文件，使用 {max_workers} 线程并发处理...")

    success_count = 0
    completed_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(process_single_file, wav, fuz, lip): wav.name
            for wav, fuz, lip in tasks
        }

        for future in concurrent.futures.as_completed(future_to_file):
            completed_count += 1
            try:
                if future.result():
                    success_count += 1
            except Exception as e:
                logger.error(f"任务执行异常: {e}")

            if completed_count % 100 == 0:
                progress = (completed_count / total_files) * 100
                logger.info(f"进度: {completed_count}/{total_files} ({progress:.1f}%)")

    logger.info(f"转换完成。成功: {success_count}/{total_files}")

    # 打包压缩
    try:
        compress_folder(COMPRESSED_DIR, str(FINAL_ARCHIVE))
        logger.info(f"最终打包完成: {FINAL_ARCHIVE}")
    except Exception as e:
        logger.error(f"压缩打包失败: {e}")

if __name__ == "__main__":
    main()
