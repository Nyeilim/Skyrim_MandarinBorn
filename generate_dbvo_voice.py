import os
import sys
import json
import subprocess
import shutil
import logging
from pathlib import Path
from filter_logic import clean_text_brackets

import struct

import re
import csv
from pypinyin import pinyin, Style

# ================= 配置区域 =================
PROJECT_ROOT = Path(__file__).parent.absolute()

# 基础路径
DBVO_ROOT = PROJECT_ROOT / "Input/DBVO_Voice"
DBVO_JSON_ROOT = DBVO_ROOT / "DragonbornVoiceOver"
DBVO_SOUND_DIR = DBVO_ROOT / "Sound/DBVO"
OUTPUT_DIR = PROJECT_ROOT / "Output_CN/Sound/DBVO"

# 工具路径
FFMPEG_LOCAL = PROJECT_ROOT / "ffmpeg/bin/ffmpeg"
# Runalip 路径 (通过 wine 调用)
RUNALIP_EXE = PROJECT_ROOT / "Tools/Runalip/Runalip.exe"
USE_WINE_FOR_RUNALIP = True

if FFMPEG_LOCAL.exists():
    FFMPEG_EXE = FFMPEG_LOCAL
else:
    FFMPEG_EXE = Path("ffmpeg")

# IndexTTS 路径
INDEXTTS_DIR = PROJECT_ROOT / "index-tts"
INDEXTTS_CHECKPOINTS = INDEXTTS_DIR / "checkpoints"
INDEXTTS_CONFIG = INDEXTTS_CHECKPOINTS / "config.yaml"

# 临时目录
TEMP_DIR = PROJECT_ROOT / "temp_dbvo_processing"

# ===========================================

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def setup_environment():
    if str(FFMPEG_EXE) != "ffmpeg" and not FFMPEG_EXE.exists():
        logger.error(f"找不到 FFmpeg: {FFMPEG_EXE}")
        sys.exit(1)

    if not shutil.which("wine"):
        global USE_WINE_FOR_RUNALIP
        USE_WINE_FOR_RUNALIP = False

    if not INDEXTTS_DIR.exists():
        logger.error(f"找不到 IndexTTS 目录: {INDEXTTS_DIR}")
        sys.exit(1)

    if str(INDEXTTS_DIR) not in sys.path:
        sys.path.insert(0, str(INDEXTTS_DIR))

    OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
    TEMP_DIR.mkdir(exist_ok=True)

def load_text_map(json_dir):
    """加载目录下所有JSON文件，构建 Filename -> ChineseText 的映射。"""
    text_map = {}
    if not json_dir.exists():
        logger.error(f"JSON 目录不存在: {json_dir}")
        return text_map

    logger.info(f"正在扫描 JSON 映射: {json_dir}")
    all_json_files = list(json_dir.glob("**/*.json"))

    zh_files = [f for f in all_json_files if 'zh' in str(f).lower() or 'cn' in str(f).lower()]
    target_files = zh_files if zh_files else all_json_files

    if not target_files:
        logger.warning("未找到任何 JSON 文件")
        return {}

    logger.info(f"选定加载 {len(target_files)} 个 JSON 文件")

    for jf in target_files:
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for cn_text, filename in data.items():
                    clean_name = filename.strip()
                    if clean_name:
                        text_map[clean_name] = cn_text
        except Exception as e:
            logger.error(f"读取 JSON 失败 {jf}: {e}")

    logger.info(f"加载了 {len(text_map)} 条映射规则")
    return text_map

def extract_fuz(fuz_path):
    """从 FUZ 提取音频数据 (通常是 XWM)"""
    try:
        with open(fuz_path, 'rb') as f:
            header = f.read(4)
            if header != b'FUZE':
                logger.error(f"不是有效的 FUZ 文件: {fuz_path.name}")
                return None

            f.read(4)
            lip_size = struct.unpack('I', f.read(4))[0]
            f.seek(lip_size, 1)
            audio_data = f.read()
            return audio_data
    except Exception as e:
        logger.error(f"读取文件失败 {fuz_path.name}: {e}")
        return None

def convert_audio_to_wav(source_path, output_wav_path):
    """将源音频转为 44.1k wav 作为 prompt"""
    temp_source = source_path
    is_temp_file = False

    if source_path.suffix.lower() == '.fuz':
        audio_data = extract_fuz(source_path)
        if not audio_data:
            return False

        temp_source = output_wav_path.with_suffix(".temp_extracted.xwm")
        with open(temp_source, 'wb') as f:
            f.write(audio_data)
        is_temp_file = True

    cmd = [
        str(FFMPEG_EXE),
        '-y', '-v', 'error',
        '-i', str(temp_source),
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
    finally:
        if is_temp_file and temp_source.exists():
            try: os.remove(temp_source)
            except: pass

def get_pinyin_text(chinese_text):
    """将中文转换为不带声调的拼音 (Runalip/FaceFX 格式)，并去除标点"""
    result = pinyin(chinese_text, style=Style.NORMAL, heteronym=False)
    pinyin_list = [item[0] for item in result]
    pinyin_str = " ".join(pinyin_list)
    clean_pinyin = re.sub(r'[^\w\s]', '', pinyin_str).strip()
    return clean_pinyin

def run_runalip(csv_rows):
    """批量生成 Lip 文件 (使用临时标准目录结构欺骗 Runalip)"""
    if not USE_WINE_FOR_RUNALIP or not RUNALIP_EXE.exists():
        logger.warning("跳过口型生成 (Runalip/Wine 不可用)。")
        return False

    if not csv_rows:
        return True

    # 1. 准备临时工作区
    workplace_dir = PROJECT_ROOT / "Temp_Runalip_Workplace_DBVO"
    voice_root = workplace_dir / "sound" / "voice"
    if workplace_dir.exists(): shutil.rmtree(workplace_dir)
    voice_root.mkdir(parents=True, exist_ok=True)

    logger.info("准备 Runalip 临时工作区...")

    # 2. 复制文件并更新 CSV
    final_csv_rows = []
    file_mapping = {}

    for row in csv_rows:
        real_wav_path = Path(row["_real_path"])
        if not real_wav_path.exists():
            continue

        fake_plugin = row["Plugin"]
        fake_voicetype = row["Voice Type"]

        target_dir = voice_root / fake_plugin / fake_voicetype
        target_dir.mkdir(parents=True, exist_ok=True)

        fake_wav_path = target_dir / row["File Name"]

        try:
            shutil.copy2(str(real_wav_path), str(fake_wav_path))
            file_mapping[str(fake_wav_path.with_suffix('.lip'))] = str(real_wav_path.with_suffix('.lip'))

            clean_row = row.copy()
            del clean_row["_real_path"]
            final_csv_rows.append(clean_row)
        except Exception as e:
            logger.warning(f"复制文件失败: {e}")

    # 3. 生成 CSV
    runalip_csv_path = workplace_dir / "runalip_list.csv"
    csv_headers = ["State", "Plugin", "File Name", "Voice Type", "Dialogue 1", "Dialogue 2"]

    with open(runalip_csv_path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=csv_headers, lineterminator='\r\n')
        writer.writeheader()
        writer.writerows(final_csv_rows)

    # 4. 临时输出目录
    lip_gen_dir = PROJECT_ROOT / "Temp_DBVO_Lip_Output"
    if lip_gen_dir.exists(): shutil.rmtree(lip_gen_dir)
    lip_gen_dir.mkdir(exist_ok=True)

    # 5. 命令构造 (通过 wine 调用)
    cmd = [
        "wine", str(RUNALIP_EXE), "-genlips", "SSE",
        str(runalip_csv_path),
        str(voice_root),
        str(lip_gen_dir)
    ]

    logger.info("启动 Runalip 生成口型...")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', cwd=workplace_dir)

        count = 0
        for line in proc.stdout:
            count += 1
            if count < 10 or count % 100 == 0:
                print(f"[Runalip] {line.strip()}")

        proc.wait()

        # 6. 将生成的 LIP 移回真实目录
        logger.info("正在将 LIP 文件部署回原位...")
        move_count = 0

        for generated_lip in lip_gen_dir.rglob("*.lip"):
            rel_path = generated_lip.relative_to(lip_gen_dir)
            expected_fake_lip = voice_root / rel_path
            real_lip_path_str = file_mapping.get(str(expected_fake_lip))

            if real_lip_path_str:
                target_lip = Path(real_lip_path_str)
                target_lip.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(generated_lip), str(target_lip))
                move_count += 1

        logger.info(f"Runalip 完成，成功部署 {move_count} 个 Lip 文件。")

    except Exception as e:
        logger.error(f"Runalip 执行失败: {e}")
    finally:
        if workplace_dir.exists(): shutil.rmtree(workplace_dir)
        if lip_gen_dir.exists(): shutil.rmtree(lip_gen_dir)

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

    # 1. 加载映射
    filename_to_text = load_text_map(DBVO_JSON_ROOT)
    if not filename_to_text:
        logger.error("未找到有效的文本映射，退出。")
        return

    # 2. 扫描源音频文件
    logger.info(f"正在扫描源音频: {DBVO_SOUND_DIR}")
    tasks = []

    if not DBVO_SOUND_DIR.exists():
        logger.error(f"源音频目录不存在: {DBVO_SOUND_DIR}")
        return

    for file_path in DBVO_SOUND_DIR.rglob("*"):
        if file_path.suffix.lower() not in ['.fuz', '.wav']:
            continue
        if file_path.is_file():
            stem = file_path.stem
            cn_text = filename_to_text.get(stem)

            if cn_text:
                tasks.append({
                    'src_path': file_path,
                    'text': cn_text,
                    'stem': stem
                })

    if not tasks:
        logger.info("没有找到需要处理的文件 (文件名匹配失败或目录为空)。")
        return

    logger.info(f"找到 {len(tasks)} 个待处理文件。")

    # 3. 初始化模型
    try:
        tts_model = init_indextts()
    except Exception as e:
        logger.error(f"模型加载失败: {e}")
        return

    success_count = 0
    runalip_rows = []

    # 4. 执行生成
    for i, task in enumerate(tasks):
        src_path = task['src_path']
        cn_text = task['text']
        stem = task['stem']

        rel_path = src_path.relative_to(DBVO_SOUND_DIR)

        cleaned_text, is_pure_action = clean_text_brackets(cn_text)
        if is_pure_action or not cleaned_text:
            logger.info(f"[{i+1}/{len(tasks)}] 跳过 (纯动作/无文本): {stem} -> {cn_text}")
            continue

        target_wav_path = OUTPUT_DIR / rel_path.with_suffix('.wav')
        target_wav_path.parent.mkdir(parents=True, exist_ok=True)

        group_id = rel_path.parts[0] if len(rel_path.parts) > 1 else "Root"

        pinyin_text = get_pinyin_text(cleaned_text)
        runalip_rows.append({
            "State": "",
            "Plugin": "DBVO_Fake_Plugin",
            "File Name": target_wav_path.name,
            "Voice Type": group_id,
            "Dialogue 1": "",
            "Dialogue 2": pinyin_text,
            "_real_path": str(target_wav_path)
        })

        if target_wav_path.exists():
            success_count += 1
            continue

        temp_prompt = TEMP_DIR / f"prompt_{i}.wav"

        try:
            if not convert_audio_to_wav(src_path, temp_prompt):
                continue

            logger.info(f"[{i+1}/{len(tasks)}] 生成: {stem} -> {cleaned_text}")

            original_cwd = os.getcwd()
            os.chdir(INDEXTTS_DIR)

            try:
                tts_model.infer(
                    spk_audio_prompt=str(temp_prompt),
                    text=cleaned_text,
                    output_path=str(target_wav_path),
                    use_random=False,
                    verbose=False,
                    speed=1.0
                )
                success_count += 1
            except Exception as e:
                logger.error(f"  TTS 生成出错: {e}")
            finally:
                os.chdir(original_cwd)

        except Exception as e:
            logger.error(f"  处理异常: {e}")
        finally:
            if temp_prompt.exists():
                try: os.remove(temp_prompt)
                except: pass

    # 5. 批量生成 LIP
    if runalip_rows:
        logger.info(f"正在为 {len(runalip_rows)} 个文件生成 LIP...")
        run_runalip(runalip_rows)

    # 清理
    try: shutil.rmtree(TEMP_DIR)
    except: pass

    logger.info(f"处理完成！成功生成语音: {success_count}/{len(tasks)}")

if __name__ == "__main__":
    main()
