# coding: utf-8

# https://github.com/HaujetZhao/Chinese-ITN/blob/master/chinese_itn.py

"""
中文数字转阿拉伯数字 (Chinese ITN - Inverse Text Normalization)

用于把语音识别出的中文数字转为阿拉伯数字形式，
使用正则表达式进行匹配和替换。

用法示例：
    from chinese_itn import chinese_to_num

    res = chinese_to_num('幺九二点幺六八点幺点幺')
    print(res)  # 192.168.1.1

    res = chinese_to_num('三五百人')
    print(res)  # 300~500人
"""

__all__ = ["chinese_to_num"]

import re

# ============================================================
# 第一部分：配置和映射表
# ============================================================

# 单位映射：中文单位 -> 映射后的单位（None表示保留原样）
unit_mapping = {
    "个": None,
    "只": None,
    "分": None,
    "万": None,
    "亿": None,
    "秒": None,
    "年": None,
    "月": None,
    "日": None,
    "天": None,
    "时": None,
    "钟": None,
    "人": None,
    "层": None,
    "楼": None,
    "倍": None,
    "块": None,
    "次": None,
    "克": "g",
    # ported from upstream a3bbee8: 斤、两加入单位表
    "两": None,
    "斤": None,
    "千克": "kg",
    "米": "米",
    "千米": "千米",
    "千米每小时": "km/h",
}

# 生成单位正则（按长度从长到短排序，确保先匹配长的）
_sorted_units = sorted(unit_mapping.keys(), key=len, reverse=True)
common_units = "|".join(f"{u}" for u in _sorted_units)

# 中文数字映射表
num_mapper = {
    "零": "0",
    "一": "1",
    "幺": "1",
    "二": "2",
    "两": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
    "点": ".",
}

# 中文数字对数值的映射
value_mapper = {
    "零": 0,
    "一": 1,
    # ported from upstream 7d7fac3: 幺纳入数值映射（更正省略尾随单位提交一并修正）
    "幺": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "百": 100,
    "千": 1000,
    "万": 10000,
    "亿": 100000000,
}

# 成语和习语黑名单
idioms = """
正经八百  五零二落 五零四散 
五十步笑百步 乌七八糟 污七八糟 四百四病 思绪万千 
十有八九 十之八九 三十而立 三十六策 三十六计 三十六行
三五成群 三百六十行 三六九等 
七老八十 七零八落 七零八碎 七七八八 乱七八遭 乱七八糟 略知一二 零零星星 零七八碎 
九九归一 二三其德 二三其意 无银三百两 八九不离十 
百分之百 年三十 烂七八糟 一点一滴 路易十六 九三学社 五四运动 入木三分 三十六计 
九九八十一 三七二十一  
十二五 十三五 十四五 十五五 十六五 十七五 十八五
""".split()

# 模糊表达黑名单（包含"几"的表达不转换）
fuzzy_regex = re.compile(r"几")

# ported from upstream db3dd8f: 「百/千/万」+单个数字字作费率术语（万三=万分之三）
# 或词（万一）时不转换；仅当其前无数字或单位字时才视为术语
_wan_term = re.compile(
    r"(?<![一二两三四五六七八九零幺十百千万亿])[百千万][一二三四五六七八九]"
)

# ported from upstream 1015197: 纯单位字组合（如十百千万）不做数值转换所需集合
_digit_chars = {k for k, v in value_mapper.items() if v <= 9}
_unit_chars = {k for k, v in value_mapper.items() if v > 9}


# ============================================================
# 第二部分：范围表达式处理
# ============================================================


def _chinese_digit_to_num(char):
    """将单个中文数字转为阿拉伯数字"""
    return value_mapper.get(char, 0)


def _parse_tens(tens):
    """解析"十"或"X十"格式的数值"""
    return 10 if tens == "十" else _chinese_digit_to_num(tens[0]) * 10


# 范围表达式模式
_range_pattern_1 = re.compile(
    r"([二三四五六七八九])([二三四五六七八九])([十百千万亿])([万千百亿])?"
)
_range_pattern_2 = re.compile(
    r"(十|[一二三四五六七八九十]+[十百千万])([一二三四五六七八九])([一二三四五六七八九])([万千亿])?"
)
_range_pattern_3 = re.compile(r"^([一二三四五六七八九])([一二三四五六七八九])$")


def _convert_range_pattern_1(match):
    """转换模式1: 三五百 → 300~500, 五六十 → 50~60, 三四十万 → 30~40万"""
    groups = match.groups()
    d1, d2, unit = groups[0], groups[1], groups[2]
    suffix_unit = groups[3] if len(groups) > 3 and groups[3] else ""

    v1 = _chinese_digit_to_num(d1)
    v2 = _chinese_digit_to_num(d2)

    if unit == "十":
        v1, v2 = v1 * 10, v2 * 10
        return f"{v1}~{v2}{suffix_unit}"
    elif unit in ["万", "亿"]:
        return f"{v1}~{v2}{unit}{suffix_unit}"
    elif unit == "千" and suffix_unit:
        return f"{v1}~{v2}{unit}{suffix_unit}"
    else:
        v1 = v1 * value_mapper[unit]
        v2 = v2 * value_mapper[unit]
        return f"{v1}~{v2}{suffix_unit}"


def _convert_range_pattern_2(match):
    """转换模式2: 十五六 → 15~16, 四十五六万 → 45~46万, 一百六七 → 160~170"""
    groups = match.groups()
    base_part, d1, d2 = groups[0], groups[1], groups[2]
    unit = groups[3] if len(groups) > 3 and groups[3] else ""

    last_char = base_part[-1]

    # 计算基数值
    if last_char == "十":
        base_value = (
            10 if len(base_part) == 1 else _chinese_digit_to_num(base_part[0]) * 10
        )
    elif last_char in value_mapper:
        num_part = base_part[:-1]
        base_value = (
            _chinese_digit_to_num(num_part[0]) * value_mapper[last_char]
            if num_part
            else value_mapper[last_char]
        )
    else:
        base_value = _parse_tens(base_part)

    num1 = _chinese_digit_to_num(d1)
    num2 = _chinese_digit_to_num(d2)
    multiplier = value_mapper.get(last_char, 10) // 10

    return f"{base_value + num1 * multiplier}~{base_value + num2 * multiplier}{unit}"


def _convert_range_pattern_3(match):
    """转换模式3: 三四 → 3~4, 五六 → 5~6"""
    d1, d2 = match.groups()
    v1 = _chinese_digit_to_num(d1)
    v2 = _chinese_digit_to_num(d2)
    return f"{v1}~{v2}"


def is_range_expression(text):
    """判断是否为范围表达式"""
    sorted_units = sorted(unit_mapping.keys(), key=len, reverse=True)
    unit_pattern = "|".join(re.escape(u) for u in sorted_units)
    optional_unit = rf"(?:{unit_pattern})?"

    range_pattern = re.compile(rf"""(?x)
        (?<!点)
        (?:
            [二三四五六七八九]{{2}}(?:十|[百千万亿]){optional_unit}
            |
            [一二三四五六七八九]?十[一二三四五六七八九]{{2}}(?:[万千亿]|{optional_unit})
            |
            [一二三四五六七八九][百千][二三四五六七八九]{{2}}十
            |
            [一二三四五六七八九十]+[万千百][一二三四五六七八九]{{2}}{optional_unit}
        )
    """)

    # 只认「整串」范围表达式（三五百/十五六/三四十万…），
    # 避免把连续数字序列（三百零五七百/三十五六七八）中的子串误判成范围
    return range_pattern.fullmatch(text) is not None


def convert_range_expression(text):
    """转换范围表达式"""
    # 剥离单位（复用主文件的 strip_unit 函数）
    stripped_text = text
    mapped_unit = ""

    numeric_units = {"万", "亿", "千", "百", "十"}
    sorted_units = sorted(unit_mapping.keys(), key=len, reverse=True)

    for unit_cn in sorted_units:
        if unit_cn in numeric_units:
            continue
        if text.endswith(unit_cn):
            stripped_text = text[: -len(unit_cn)]
            mapped_unit = unit_mapping[unit_cn]
            if mapped_unit is None:
                mapped_unit = unit_cn
            break

    # 匹配范围表达式模式
    match = _range_pattern_2.search(stripped_text)
    if match:
        return _convert_range_pattern_2(match) + mapped_unit

    match = _range_pattern_1.search(stripped_text)
    if match:
        return _convert_range_pattern_1(match) + mapped_unit

    match = _range_pattern_3.search(stripped_text)
    if match:
        return _convert_range_pattern_3(match) + mapped_unit

    return text


# ============================================================
# 第三部分：正则表达式模式定义
# ============================================================

# 用于去除末尾单位的正则
_unit_suffix_pattern = re.compile(rf"({common_units}|[a-zA-Z]+)$")

# 总模式，筛选出可能需要替换的内容
# ported from upstream 0fcb423: 主体可选 "[正负]" 前缀并新增正负号分支，识别正数/负数
pattern = re.compile(rf"""(?ix)
([a-z]\s*)?
(
  (?:
    [正负]?
    (
      [几零幺一二两三四五六七八九十百千万点比]
      |[零一二三四五六七八九十][ ]
      |(?<=[一二两三四五六七八九十])[年月日号分]
      |(分之)
    )+
    (
      (?<=[一二两三四五六七八九十])([a-zA-Z年月日号]|{common_units})
      |(?<=[一二两三四五六七八九十]\s)[a-zA-Z]
    )?
    (?(1)
    |(?(5)
      |(
        [零幺一二两三四五六七八九十百千万亿点比]
        |(分之)
      )
    )+
    )
  )
  |
  (?:
    [正负][零幺一二两三四五六七八九十百千万点]
  )
)
""")

# 纯数字序号
pure_num = re.compile(
    f"[零幺一二三四五六七八九]+(点[零幺一二三四五六七八九]+)* *([a-zA-Z]|{common_units})?"
)

# 数值
value_num = re.compile(
    f"十?(零?[一二两三四五六七八九十][十百千万]{{1,2}})*零?十?[一二三四五六七八九]?(点[零一二三四五六七八九]+)? *([a-zA-Z]|{common_units})?"
)

# 百分值
percent_value = re.compile(
    "(?<![一二三四五六七八九])(百分之)[零一二三四五六七八九十百千万]+(点)?(?(2)[零一二三四五六七八九]+)"
)

# 分数
fraction_value = re.compile(
    "([零一二三四五六七八九十百千万]+(点)?(?(2)[零一二三四五六七八九]+))分之([零一二三四五六七八九十百千万]+(点)?(?(4)[零一二三四五六七八九]+))"
)

# 比值
ratio_value = re.compile(
    "([零一二三四五六七八九十百千万]+(点)?(?(2)[零一二三四五六七八九]+))比([零一二三四五六七八九十百千万]+(点)?(?(4)[零一二三四五六七八九]+))"
)

# 时间
time_value = re.compile(
    "[零一二两三四五六七八九十]+点([零一二三四五六七八九十]+分)([零一二三四五六七八九十]+秒)?"
)

# 日期
data_value = re.compile(
    "([零一二三四五六七八九十]+年)?([一二三四五六七八九十]+月)?([一二三四五六七八九十]+[日号])?"
)


# ============================================================
# 第四部分：辅助函数
# ============================================================


def strip_trailing_unit(text):
    """用正则去除末尾的单位"""
    match = _unit_suffix_pattern.search(text)
    if match:
        return text[: match.start()]
    return text


# ============================================================
# 连续数字序列拆分（局部移植自 upstream a589dfb sequence_parser 的
# 词法/解析核心，仅保留基础数字 Token 集）。只对「一个匹配内解析出
# >=2 个独立数字」的序列生效（十二十三十/三百零五七百/三十五六七八）；
# 单个数字（二千二 等）不在此分支处理，落回后面的数值分支。
# ============================================================

_SEQ_RULES = [
    ("DIGIT", "[一二两三四五六七八九幺]"),
    ("TEN", "十"),
    ("HUNDRED", "百"),
    ("THOUSAND", "千"),
    ("TEN_THOUSAND", "万"),
    ("HUNDRED_MILLION", "亿"),
    ("ZERO", "零"),
    ("WHITESPACE", r"\s+"),
    ("OTHER", "."),
]
_seq_lexer = re.compile("|".join(f"(?P<{n}>{p})" for n, p in _SEQ_RULES))
_BASIC_SEQ_TYPES = {
    "DIGIT", "TEN", "HUNDRED", "THOUSAND", "TEN_THOUSAND", "HUNDRED_MILLION", "ZERO",
}
_SEQ_VALUE_MAP = {
    "零": 0, "一": 1, "幺": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
    "十": 10, "百": 100, "千": 1000, "万": 10000, "亿": 100000000,
}


def _seq_tokenize(text):
    """词法切分；若含任何非基础数字 Token（点/分之/比/年月日等）返回 None"""
    tokens = []
    for match in _seq_lexer.finditer(text):
        token_type = match.lastgroup
        if token_type == "WHITESPACE":
            continue
        if token_type == "OTHER" or token_type not in _BASIC_SEQ_TYPES:
            return None
        tokens.append((token_type, _SEQ_VALUE_MAP[match.group(token_type)]))
    return tokens


def _seq_parse_atomic(tokens, i):
    """从位置 i 解析一个原子数值，返回 (值, 消耗_token数) 或 None"""
    n = len(tokens)
    if i >= n:
        return None
    t, v = tokens[i]

    if t == "DIGIT":
        if i + 1 < n and tokens[i + 1][0] == "HUNDRED_MILLION":
            return (v * 100000000, 2)
        if i + 1 < n and tokens[i + 1][0] == "TEN_THOUSAND":
            return (v * 10000, 2)
        if i + 1 < n and tokens[i + 1][0] == "THOUSAND":
            return (v * 1000, 2)
        if i + 1 < n and tokens[i + 1][0] == "HUNDRED":
            base = v * 100
            consumed = 2
            j = i + 2
            if j < n and tokens[j][0] == "ZERO":
                if j + 1 < n and tokens[j + 1][0] == "DIGIT":
                    base += tokens[j + 1][1]
                    consumed += 2
            elif j < n and tokens[j][0] == "DIGIT":
                tens_d = tokens[j][1]
                if j + 1 < n and tokens[j + 1][0] == "TEN":
                    base += tens_d * 10
                    consumed += 2
                    j += 2
                    if j < n and tokens[j][0] == "DIGIT":
                        base += tokens[j][1]
                        consumed += 1
                else:
                    base += tens_d * 10
                    consumed += 1
            return (base, consumed)
        if (
            i + 2 < n
            and tokens[i + 1][0] == "TEN"
            and tokens[i + 2][0] == "DIGIT"
        ):
            if i + 3 < n and tokens[i + 3][0] == "TEN":
                pass  # 后跟 TEN → 倾向拆开
            else:
                return (10 * v + tokens[i + 2][1], 3)
        if i + 1 < n and tokens[i + 1][0] == "TEN":
            if i > 0 and tokens[i - 1][0] == "DIGIT":
                pass
            else:
                return (10 * v, 2)
        return (v, 1)

    if t == "TEN":
        if (
            i + 2 < n
            and tokens[i + 1][0] == "DIGIT"
            and tokens[i + 2][0] == "HUNDRED_MILLION"
        ):
            return ((10 + tokens[i + 1][1]) * 100000000, 3)
        if i + 1 < n and tokens[i + 1][0] == "HUNDRED_MILLION":
            return (10 * 100000000, 2)
        if i + 1 < n and tokens[i + 1][0] == "DIGIT":
            return (10 + tokens[i + 1][1], 2)
        return (10, 1)

    if t == "ZERO":
        return (0, 1)

    if t in ("HUNDRED", "THOUSAND", "TEN_THOUSAND", "HUNDRED_MILLION"):
        return (v, 1)

    return None


def _seq_build_number(tokens, i):
    """从位置 i 解析一个完整数值，返回 (值, 消耗_token数) 或 None"""
    result = _seq_parse_atomic(tokens, i)
    if result is None:
        return None
    value, consumed = result
    n = len(tokens)
    j = i + consumed

    if j < n:
        nxt = tokens[j][0]
        if nxt == "TEN_THOUSAND" and 0 < value < 10000:
            value *= 10000
            consumed += 1
            j += 1
        elif nxt == "HUNDRED_MILLION" and 0 < value < 100000000:
            value *= 100000000
            consumed += 1
            j += 1

    if value >= 10000:
        limit = 10000
    elif value >= 1000:
        limit = 1000
    else:
        limit = None

    if limit:
        while j < n:
            if tokens[j][0] == "ZERO":
                consumed += 1
                j += 1
                continue
            chunk = _seq_parse_atomic(tokens, j)
            if chunk is None:
                break
            chunk_val, chunk_con = chunk
            if chunk_val >= limit:
                break
            value += chunk_val
            consumed += chunk_con
            j += chunk_con

    if j < n:
        nxt = tokens[j][0]
        if nxt == "TEN_THOUSAND" and 0 < value < 10000:
            value *= 10000
            consumed += 1
        elif nxt == "HUNDRED_MILLION" and 0 < value < 100000000:
            value *= 100000000
            consumed += 1

    return (value, consumed)


def _seq_parse_all(tokens):
    """规约 Token 序列为阿拉伯数字列表；失败返回 None"""
    nums = []
    i = 0
    n = len(tokens)
    while i < n:
        result = _seq_build_number(tokens, i)
        if result is None:
            return None
        value, consumed = result
        nums.append(value)
        i += consumed
    return nums


def split_number_sequence(text):
    """把一个匹配内的连续数字序列拆分为空格分隔的阿拉伯数字。
    仅当解析出 >=2 个独立数字时返回，否则返回 None（单个数字交数值分支）。
    """
    stripped, unit = strip_unit(text)
    if unit in ("万", "亿"):
        stripped = text
        unit = ""
    tokens = _seq_tokenize(stripped)
    if tokens is None:
        return None
    nums = _seq_parse_all(tokens)
    if nums is None or len(nums) < 2:
        return None
    result = " ".join(str(num) for num in nums)
    if unit:
        result += unit
    return result


def is_consecutive_value(text):
    """检测是否为连续数值（一个匹配内解析出 >=2 个独立数字）"""
    return split_number_sequence(text) is not None


def split_consecutive_value(text):
    """分割连续数值为空格分隔的阿拉伯数字"""
    return split_number_sequence(text)


def strip_unit(original):
    """把数字后面跟着的单位剥离开，并应用单位映射"""
    unit_pattern = re.compile(rf"({common_units})$")
    match = unit_pattern.search(original)

    if match:
        unit_cn = match.group(1)
        stripped = original[: match.start()]
        mapped_unit = unit_mapping.get(unit_cn)
        unit = mapped_unit if mapped_unit is not None else unit_cn
    else:
        stripped = original
        unit = ""

    if not unit and stripped:
        letter_match = re.search(r"[a-zA-Z]+$", stripped)
        if letter_match:
            unit = letter_match.group()
            stripped = stripped[: letter_match.start()]

    return stripped.strip(), unit


# ============================================================
# 第五部分：转换函数
# ============================================================


def convert_pure_num(original, strict=False):
    """把中文数字转为对应的阿拉伯数字"""
    stripped, unit = strip_unit(original)
    if stripped in ["一"] and not strict:
        return original
    converted = [num_mapper[c] for c in stripped]
    return "".join(converted) + unit


def convert_value_num(original):
    """把中文数值转为阿拉伯数字"""
    stripped, unit = strip_unit(original)
    if "点" not in stripped:
        stripped += "点"
    int_part, decimal_part = stripped.split("点")
    if not int_part:
        return original

    # 计算整数部分的值
    value, temp, base = 0, 0, 1
    for c in int_part:
        if c == "十":
            temp = 10 if temp == 0 else value_mapper[c] * temp
            base = 1
        elif c == "零":
            base = 1
        elif c in "一二两三四五六七八九":
            temp += value_mapper[c]
        elif c in "万":
            value += temp
            value *= value_mapper[c]
            base = value_mapper[c] // 10
            temp = 0
        elif c in "百千":
            value += temp * value_mapper[c]
            base = value_mapper[c] // 10
            temp = 0
    value += temp * base
    final = str(value)

    # 小数部分
    decimal_str = convert_pure_num(decimal_part, strict=True)
    if decimal_str:
        final += "." + decimal_str
    final += unit

    return final


def convert_fraction_value(original):
    """转换分数"""
    # 修正千分比：千分之三 → 3‰（原逻辑把「千分」当分母，得出 3/0）
    if original.startswith("千分之"):
        return convert_value_num(original[3:]) + "‰"
    denominator, numerator = original.split("分之")
    return convert_value_num(numerator) + "/" + convert_value_num(denominator)


def convert_percent_value(original):
    """转换百分数"""
    return convert_value_num(original[3:]) + "%"


def convert_ratio_value(original):
    """转换比值"""
    num1, num2 = original.split("比")
    return convert_value_num(num1) + ":" + convert_value_num(num2)


def convert_time_value(original):
    """转换时间"""
    res = [x for x in re.split("[点分秒]", original) if x]
    final = ""
    hour = convert_value_num(res[0])
    final += hour.zfill(2)
    minute = convert_value_num(res[1])
    final += ":" + minute.zfill(2)
    if len(res) > 2:
        second = convert_value_num(res[2])
        final += ":" + second.zfill(2)
    if len(res) > 3:
        final += "." + convert_pure_num(res[3])
    return final


def convert_date_value(original):
    """转换日期"""
    final = ""
    if "年" in original:
        year, original = original.split("年")
        final += convert_pure_num(year) + "年"
    if "月" in original:
        month, original = original.split("月")
        final += convert_value_num(month) + "月"
    if "日" in original:
        day, original = original.split("日")
        final += convert_value_num(day) + "日"
    elif "号" in original:
        day, original = original.split("号")
        final += convert_value_num(day) + "号"
    return final


# ============================================================
# 第六部分：主替换逻辑
# ============================================================


def replace(original):
    """主替换函数"""
    string = original.string
    l_pos, r_pos = original.regs[2]
    l_pos = max(l_pos - 2, 0)
    head = original.group(1)
    original_text = original.group(2)
    original = original_text

    DEBUG = False

    try:
        # 成语/习语检测
        if idioms and any(
            [string.find(idiom) in range(l_pos, r_pos) for idiom in idioms]
        ):
            num_type = "成语/习语"
            final = original

        # 模糊表达检测
        elif fuzzy_regex.search(original):
            num_type = "模糊表达"
            final = original

        # ported from upstream db3dd8f: 「万」+单个数字字作费率术语或词（万一/万三）时不转换
        elif _wan_term.search(original):
            num_type = "万术语"
            final = original

        # ported from upstream 1015197: 完全由单位字组成、不含数字字且长度≥2时跳过转换
        elif (
            _unit_chars.issuperset(original)
            and len(original) >= 2
            and not any(c in _digit_chars for c in original)
        ):
            num_type = "纯单位字"
            final = original

        # ported from upstream b797a7c: 以"点"开头是动词（点击/点名），不是小数点
        elif original.startswith("点"):
            num_type = "动词点"
            final = original

        else:
            # ported from upstream 0fcb423: 提取正负号后按原有分支转换
            sign_prefix = ""
            parsed = original
            if original and original[0] in ("正", "负"):
                sign_prefix = "+" if original[0] == "正" else "-"
                parsed = original[1:]

            if parsed == "一" and sign_prefix:
                num_type = "正负数"
                final = sign_prefix + "1"

            # 范围表达式
            elif is_range_expression(parsed):
                num_type = "范围表达式"
                final = sign_prefix + convert_range_expression(parsed)

            # 时间
            elif time_value.fullmatch(parsed):
                num_type = "时间"
                final = sign_prefix + convert_time_value(parsed)

            # 纯数字
            elif pure_num.fullmatch(strip_trailing_unit(parsed)):
                num_type = "纯数字"
                final = sign_prefix + convert_pure_num(parsed)

            # 连续数值
            elif is_consecutive_value(parsed):
                num_type = "连续数值"
                final = sign_prefix + split_consecutive_value(parsed)

            # 数值
            elif value_num.fullmatch(strip_trailing_unit(parsed)):
                num_type = "数值"
                final = sign_prefix + convert_value_num(parsed)

            # 百分数
            elif percent_value.fullmatch(parsed):
                num_type = "百分之数值"
                final = sign_prefix + convert_percent_value(parsed)

            # 分数
            elif fraction_value.fullmatch(parsed):
                num_type = "分数"
                final = sign_prefix + convert_fraction_value(parsed)

            # 比值
            elif ratio_value.fullmatch(parsed):
                num_type = "比值"
                final = sign_prefix + convert_ratio_value(parsed)

            # 日期
            elif data_value.fullmatch(parsed):
                num_type = "日期"
                final = sign_prefix + convert_date_value(parsed)

            else:
                num_type = "未匹配"
                final = original

        if head:
            final = head + final

        if DEBUG and original_text != final:
            print(f"[{num_type}] {original_text} → {final}")

    except Exception as e:
        num_type = "错误"
        final = original
        if DEBUG:
            print(f"[错误] {original_text}: {e}")

    return final


# ============================================================
# 第七部分：主函数
# ============================================================


def chinese_to_num(original):
    """主函数：将中文数字转换为阿拉伯数字"""
    result = pattern.sub(replace, original)
    return result


# ============================================================
# 测试代码
# ============================================================

if __name__ == "__main__":
    print(chinese_to_num("二零二五年十月"))
    print(chinese_to_num("乱七八糟"))
