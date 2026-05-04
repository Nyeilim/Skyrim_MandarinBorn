import os
import sys
import subprocess
import csv
import tempfile
import time
import argparse
import wave
import struct
import threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from queue import Queue

# ================= 配置区域 =================
FFMPEG_REL_PATH = "ffmpeg/bin"

INPUT_DIRS_TO_CHECK = [
    Path("Input/SkyrimVoice/sound/fx"),
    Path("Input/sound/fx")
]

OUTPUT_CSV = Path("Input/Fx_Transcriptions.csv")

DEFAULT_MODEL_SIZE = "turbo"
DEFAULT_DEVICE = "cuda"
DEFAULT_COMPUTE_TYPE = "float16"
RMS_THRESHOLD = 300
# ===========================================

def setup_env():
    """配置环境：挂载 FFmpeg，尝试挂载 CUDA 库，检查 faster-whisper"""
    project_root = Path(__file__).parent.absolute()
    ffmpeg_bin = project_root / FFMPEG_REL_PATH

    # 1. 设置 PATH (FFmpeg)
    if ffmpeg_bin.exists():
        os.environ["PATH"] = str(ffmpeg_bin) + os.pathsep + os.environ["PATH"]

    # 2. 尝试挂载 index-tts 环境中的 CUDA 库 (借用已有的 Torch Lib)
    # Linux 路径: index-tts/.venv/lib/python3.x/site-packages/torch/lib
    index_tts_dir = project_root / "index-tts"
    torch_lib = None
    if (index_tts_dir / ".venv" / "lib").exists():
        # 查找 python3.x/site-packages/torch/lib
        for d in (index_tts_dir / ".venv" / "lib").iterdir():
            candidate = d / "site-packages" / "torch" / "lib"
            if candidate.exists():
                torch_lib = candidate
                break

    if torch_lib and torch_lib.exists():
        os.environ["LD_LIBRARY_PATH"] = str(torch_lib) + os.pathsep + os.environ.get("LD_LIBRARY_PATH", "")

    # 3. 检查依赖
    try:
        from faster_whisper import WhisperModel
        return WhisperModel
    except ImportError:
        print("\n[Error] 未找到 faster-whisper 库。")
        print("请运行: uv add faster-whisper")
        sys.exit(1)

def convert_to_wav(source_path):
    """将音频转换为 wav (16k, mono)。"""
    fd, temp_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(source_path),
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        str(temp_path)
    ]
    try:
        subprocess.run(cmd, check=True)

        # 检查是否静音
        is_quiet = False
        try:
            with wave.open(temp_path, 'rb') as wf:
                frames = wf.readframes(wf.getnframes())
                if len(frames) > 0:
                    rms = calculate_rms(frames, wf.getsampwidth())
                    if rms < RMS_THRESHOLD:
                        is_quiet = True
                else:
                    is_quiet = True
        except Exception:
            pass

        return True, temp_path, is_quiet
    except Exception:
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False, None, False

def calculate_rms(frames, sample_width):
    """计算音频帧的 RMS 值 (替代 audioop.rms，该模块在 Python 3.13 中已移除)"""
    n_samples = len(frames) // sample_width
    if n_samples == 0:
        return 0
    total = 0
    for i in range(n_samples):
        start = i * sample_width
        sample = int.from_bytes(frames[start:start + sample_width], byteorder='little', signed=True)
        total += sample * sample
    return int((total / n_samples) ** 0.5)

def is_hallucination(text):
    """检查是否是 Whisper 常见的幻觉文本"""
    if not text:
        return True, "Empty"

    text_lower = text.lower().strip()

    if len(text_lower) < 2:
        return True, "Too_Short"

    blacklist = [
        "subtitle by", "amara.org", "thank you", "thanks for watching",
        "mbc", "tbs", "..."
    ]
    for b in blacklist:
        if b in text_lower:
            return True, "Blacklisted_Word"

    return False, None

def process_batch(model, batch_files, result_queue):
    """批量处理逻辑"""
    ready_to_infer = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_file = {executor.submit(convert_to_wav, fp): fp for fp in batch_files}

        for future in as_completed(future_to_file):
            file_path = future_to_file[future]
            try:
                success, temp_wav, is_quiet = future.result()
                if success:
                    if is_quiet:
                        os.remove(temp_wav)
                        pass
                    else:
                        ready_to_infer.append((file_path, temp_wav))
            except Exception as e:
                print(f"[Warn] 转码失败 {file_path}: {e}")

    for file_path, temp_wav in ready_to_infer:
        try:
            segments, _ = model.transcribe(
                temp_wav,
                beam_size=5,
                language="en",
                condition_on_previous_text=False
            )

            text = " ".join([s.text for s in segments]).strip()

            is_bad, reason = is_hallucination(text)
            status = "Review_Needed"
            if is_bad:
                status = f"Auto_Filtered_{reason}"

            try:
                rel_path = file_path.relative_to(Path("Input"))
            except ValueError:
                rel_path = file_path

            result = {
                "RelativePath": str(rel_path).replace("\\", "/"),
                "FileName": file_path.name,
                "OriginalText": text,
                "TranslatedText": "",
                "Status": status
            }
            result_queue.put(result)

        except Exception as e:
            print(f"[Error] 推理失败 {file_path.name}: {e}")
        finally:
            if os.path.exists(temp_wav):
                os.remove(temp_wav)

def main():
    parser = argparse.ArgumentParser(description="FX Audio Scanner with Faster-Whisper")
    parser.add_argument("--model", default=DEFAULT_MODEL_SIZE, help="Model size")
    parser.add_argument("--device", default=DEFAULT_DEVICE, help="Device (cpu, cuda)")
    parser.add_argument("--compute_type", default=DEFAULT_COMPUTE_TYPE, help="Compute type")
    args = parser.parse_args()

    WhisperModel = setup_env()

    input_dir = None
    for d in INPUT_DIRS_TO_CHECK:
        if d.exists():
            input_dir = d
            break

    if not input_dir:
        print(f"[Error] 找不到输入目录")
        return

    print(f"[Info] 模型: {args.model} | 设备: {args.device} | 计算类型: {args.compute_type}")

    start_time = time.time()

    try:
        model = WhisperModel(args.model, device=args.device, compute_type=args.compute_type)
    except Exception as e:
        print(f"[Error] 模型加载失败: {e}")
        if args.device == "cuda":
            print("尝试回退到 CPU (int8)...")
            try:
                model = WhisperModel(args.model, device="cpu", compute_type="int8")
            except Exception as e2:
                 print(f"[Fatal] CPU 回退也失败: {e2}")
                 return
        else:
            return

    exts = {'.wav', '.mp3', '.xwm'}
    files = list(input_dir.rglob("*"))
    audio_files = [f for f in files if f.suffix.lower() in exts]
    total = len(audio_files)

    print(f"[Info] 找到 {total} 个音频文件，开始处理...")

    results = []
    result_queue = Queue()

    BATCH_SIZE = 10
    processed_count = 0

    for i in range(0, total, BATCH_SIZE):
        batch = audio_files[i : i + BATCH_SIZE]
        process_batch(model, batch, result_queue)

        while not result_queue.empty():
            results.append(result_queue.get())

        processed_count += len(batch)
        print(f"\r进度: {processed_count}/{total} | 已识别: {len(results)}", end="", flush=True)

    duration = time.time() - start_time
    print(f"\n\n[Success] 完成！耗时: {duration:.2f}秒 (平均 {duration/total if total else 0:.2f}s/个)")

    if results:
        with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8-sig') as f:
            fieldnames = ["RelativePath", "FileName", "OriginalText", "TranslatedText", "Status"]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(results)
        print(f"已生成: {OUTPUT_CSV}")
    else:
        print("没有生成有效结果 (可能全是静音或被过滤)。")

if __name__ == "__main__":
    main()
