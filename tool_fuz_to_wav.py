import os
import sys
import struct
import subprocess
from pathlib import Path

# ffmpeg: 优先使用项目目录下的，否则用系统 PATH
PROJECT_ROOT = Path(__file__).parent.absolute()
FFMPEG_LOCAL = PROJECT_ROOT / "ffmpeg" / "bin" / "ffmpeg"
FFMPEG_EXE = FFMPEG_LOCAL if FFMPEG_LOCAL.exists() else "ffmpeg"


def extract_fuz(fuz_path):
    """从 FUZ 提取音频数据 (通常是 XWM)"""
    try:
        with open(fuz_path, 'rb') as f:
            header = f.read(4)
            if header != b'FUZE':
                print(f"[Error] 不是有效的 FUZ 文件: {fuz_path.name}")
                return None

            f.read(4)
            lip_size = struct.unpack('I', f.read(4))[0]
            f.seek(lip_size, 1)
            audio_data = f.read()
            return audio_data
    except Exception as e:
        print(f"[Error] 读取文件失败 {fuz_path.name}: {e}")
        return None

def convert_to_wav(audio_data, output_wav_path):
    """将音频数据转为 WAV"""
    temp_xwm = output_wav_path.with_suffix(".temp.xwm")
    with open(temp_xwm, 'wb') as f:
        f.write(audio_data)

    cmd = [
        str(FFMPEG_EXE), "-y", "-v", "error",
        "-i", str(temp_xwm),
        str(output_wav_path)
    ]

    try:
        subprocess.run(cmd, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[Error] FFmpeg 转换失败: {e}")
        return False
    finally:
        if temp_xwm.exists():
            try:
                os.remove(temp_xwm)
            except:
                pass

def main():
    if len(sys.argv) < 2:
        print("用法: python tool_fuz_to_wav.py <fuz文件路径...>")
        return

    count = 0
    for file_path_str in sys.argv[1:]:
        fuz_path = Path(file_path_str)

        if not fuz_path.exists():
            continue

        if fuz_path.suffix.lower() != '.fuz':
            if fuz_path.suffix.lower() == '.xwm':
                 print(f"正在处理 XWM: {fuz_path.name} ...")
                 wav_path = fuz_path.with_suffix('.wav')
                 with open(fuz_path, 'rb') as f:
                     data = f.read()
                 if convert_to_wav(data, wav_path):
                     print(f"  -> 生成: {wav_path.name}")
                     count += 1
                 continue

            print(f"[Skip] 不是 fuz/xwm 文件: {fuz_path.name}")
            continue

        print(f"正在处理 FUZ: {fuz_path.name} ...")

        audio_data = extract_fuz(fuz_path)
        if audio_data:
            wav_path = fuz_path.with_suffix('.wav')
            if convert_to_wav(audio_data, wav_path):
                print(f"  -> 生成: {wav_path.name}")
                count += 1

    print(f"\n完成! 共转换 {count} 个文件。")

if __name__ == "__main__":
    main()
