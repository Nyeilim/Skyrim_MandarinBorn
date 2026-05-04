import re
import logging
import csv
from pathlib import Path

# 配置日志
logger = logging.getLogger(__name__)

# 加载 Special.csv 中的屏蔽文本
BLOCKED_TEXTS = set()
PROJECT_ROOT = Path(__file__).resolve().parent
# 指向 Output_CN/Special.csv
BLOCKLIST_FILE = PROJECT_ROOT / "Output_CN" / "Special.csv"

def load_blocklist():
    """加载屏蔽词列表 (单例模式)"""
    if BLOCKED_TEXTS:
        return

    if not BLOCKLIST_FILE.exists():
        # logger.warning(f"屏蔽列表文件不存在: {BLOCKLIST_FILE}")
        return

    try:
        with open(BLOCKLIST_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 同时加载 Dialogue 1 (原始中文) 和 Dialogue 2 (可能已被修改或注音的文本)
                # 以确保覆盖全面
                text1 = row.get('Dialogue 1 - English', '').strip()
                if text1:
                    BLOCKED_TEXTS.add(text1)
                    
                # 有时候 Special.csv 里的文本可能和 Input CSV 里的有细微差别
                # 这里我们假设只要出现在 Special.csv 里的任何文本列，都视为语气词
                # 注意：Generate_Special.csv 过程生成的 Special.csv 应该包含这些语气词
                
        # logger.info(f"已加载 {len(BLOCKED_TEXTS)} 条屏蔽文本")
    except Exception as e:
        logger.error(f"加载屏蔽列表失败: {e}")

# 模块导入时尝试加载 (或者也可以懒加载)
load_blocklist()

def clean_text_brackets(text):
    """
    去除文本中的括号及内容 (中英文括号) 以及星号动作描述 (*...*)
    返回: (清洗后的文本, 是否原本全是动作描述)
    """
    if not text:
        return "", True
        
    # 统一括号
    text = text.replace('（', '(').replace('）', ')')
    
    # 1. 去除 (...) 内容
    cleaned = re.sub(r'\(.*?\)', ' ', text)
    
    # 2. 去除 *...* 内容 (处理 *咳咳* 这种动作描述)
    cleaned = re.sub(r'\*.*?\*', ' ', cleaned)
    
    # 合并可能产生的多余空格
    cleaned = re.sub(r'\s+', ' ', cleaned)
    
    # 检查剩余内容是否有效 (包含汉字或字母)
    has_content = bool(re.search(r'[\u4e00-\u9fffA-Za-z0-9]', cleaned))
    
    return cleaned.strip(), not has_content

def should_skip_voice(file_name, raw_text, voice_type=None, dialogue_2=None):
    """
    统一的语音过滤逻辑。
    
    参数:
    file_name (str): 文件名 (例如 "abc.wav" 或 "abc")
    raw_text (str): 原始对话文本
    voice_type (str, optional): 声音类型
    dialogue_2 (str, optional): 备用对话列
    
    返回: 
    (should_skip: bool, reason: str, cleaned_text: str)
    """
    # 确保文件名不含路径
    if "\\" in file_name or "/" in file_name:
        file_name = file_name.replace("\\", "/").split("/")[-1]
        
    cleaned_text, is_pure_action = clean_text_brackets(raw_text)
    
    # 逻辑1: 纯动作/语气词 (原有逻辑)
    if is_pure_action:
        return True, "纯动作/语气词", cleaned_text
        
    # 逻辑2: 文件名包含 "voicepower" (不区分大小写)
    if "voicepower" in file_name.lower():
        return True, "文件名包含 voicepower", cleaned_text

    # 逻辑3: 文件名包含 "songs__" (唱歌文件，两个下划线)
    if "songs__" in file_name.lower():
        return True, "文件名包含 songs__ (唱歌)", cleaned_text
        
    # 逻辑4: 文本匹配 Special.csv 中的语气词
    # 使用 raw_text 进行匹配，因为 Blocklist 是从 raw text 提取的
    # [FIX] 同时也检查 cleaned_text，因为有时候 Special.csv 里存的是清洗过的，或者反之
    if (raw_text and raw_text.strip() in BLOCKED_TEXTS) or \
       (cleaned_text and cleaned_text in BLOCKED_TEXTS):
        return True, "文本匹配 Special.csv (语气词)", cleaned_text
    
    # 逻辑5: 文本包含特定唱歌标记 (如 "*唱歌*")
    # 忽略大小写
    if "*唱歌*" in raw_text or "*sings*" in raw_text.lower():
        return True, "文本包含唱歌标记", cleaned_text
    
    return False, None, cleaned_text
