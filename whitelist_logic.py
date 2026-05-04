import csv
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent
WHITELIST_FILE = PROJECT_ROOT / "Input" / "Whitelist.csv"

_WHITELIST_DATA = None

def load_whitelist():
    global _WHITELIST_DATA
    if _WHITELIST_DATA is not None:
        return

    _WHITELIST_DATA = set()
    
    if not WHITELIST_FILE.exists():
        # logger.warning(f"白名单文件不存在: {WHITELIST_FILE} (将不启用白名单功能)")
        return

    try:
        with open(WHITELIST_FILE, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            count = 0
            for row in reader:
                # Key: (stem_filename, voice_type, plugin)
                # 统一转小写
                fname = row.get('File Name', '').strip()
                if not fname:
                    continue
                
                stem = Path(fname).stem.lower()
                vtype = row.get('Voice Type', '').strip().lower()
                plugin = row.get('Plugin', '').strip().lower()
                
                # 我们使用 VoiceType + FileName + Plugin 唯一确定
                # 存储 tuple
                _WHITELIST_DATA.add((stem, vtype, plugin))
                count += 1
                
        if count > 0:
            logger.info(f"已加载白名单，包含 {count} 条记录。")
        
    except Exception as e:
        logger.error(f"加载白名单失败: {e}")

def is_in_whitelist(file_name, voice_type, plugin=""):
    """
    检查文件是否在白名单中
    file_name: 文件名 (如 abc.wav)
    voice_type: 声音类型 (文件夹名)
    plugin: 插件名 (如 skyrim.esm)
    """
    load_whitelist()
    
    if not _WHITELIST_DATA:
        return False
        
    stem = Path(file_name).stem.lower()
    vtype = voice_type.strip().lower() if voice_type else ""
    plugin_val = plugin.strip().lower() if plugin else ""
    
    # 1. 尝试完整匹配 (FileName + VoiceType + Plugin)
    if (stem, vtype, plugin_val) in _WHITELIST_DATA:
        return True
        
    # 2. 向后兼容：如果白名单里 Plugin 为空，或者调用时没传 Plugin，
    #    尝试只匹配 (FileName, VoiceType, "") 或 (FileName, VoiceType, *)
    #    这里为了安全，如果传入了 Plugin，我们优先要求精确匹配。
    #    但如果 CSV 里没写 Plugin (旧格式)，我们是否允许匹配？
    #    假设白名单必须精确。如果 CSV 里 Plugin 为空字符串，则匹配任意 Plugin?
    #    暂定策略：严格匹配。如果用户没填 Plugin，那就只能匹配 Plugin 为空的记录。
    #    
    #    不过考虑到用户可能通过 LazyVoiceFinder 导出，Plugin 肯定有。
    
    #    补充逻辑：遍历白名单，看是否有 (stem, vtype) 匹配且白名单中 plugin 为空的条目 (通配符模式)
    for (w_stem, w_vtype, w_plugin) in _WHITELIST_DATA:
        if w_stem == stem and w_vtype == vtype and not w_plugin:
             return True
             
    return False

