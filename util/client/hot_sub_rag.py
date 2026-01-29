# coding: utf-8

# https://github.com/HaujetZhao/CapsWriter-Offline/blob/master/util/hotword/hotword_standalone.py
"""
CapsWriter-Offline 独立热词与纠错系统 (Portable Standalone)
整合了最新的音素处理、相似度算法、FastRAG 加速检索
"""

import re
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Literal, NamedTuple, Optional, Tuple

import numpy as np
from loguru import logger
from loguru import logger as default_logger
from loguru._logger import Logger
from numba import njit
from pypinyin import Style, pinyin
from rich import box
from rich.console import Console
from rich.rule import Rule
from rich.table import Table

# 配置日志


# 配置控制台
console = Console()

# =============================================================================
# 1. 核心模型与音素处理 (algo_phoneme)
# =============================================================================


@dataclass(frozen=True, slots=True)
class Phoneme:
    value: str
    lang: Literal["zh", "en", "num", "other"]
    is_word_start: bool = False
    is_word_end: bool = False
    char_start: int = 0
    char_end: int = 0

    @property
    def is_tone(self) -> bool:
        return self.value.isdigit()

    @property
    def info(self) -> Tuple[str, str, bool, bool, bool, int, int]:
        return (
            self.value,
            self.lang,
            self.is_word_start,
            self.is_word_end,
            self.is_tone,
            self.char_start,
            self.char_end,
        )


def normalize_text(text: str) -> str:
    """
    对输入文本进行标准化处理，将大写字母转换为小写，并在字母与数字之间插入空格分隔符

    Args:
        text (str): 待处理的原始文本

    Returns:
        str: 标准化后的文本
    """
    result = []
    prev_char = ""
    for char in text:
        if char.isalnum() or "\u4e00" <= char <= "\u9fff":
            if char.isupper() and prev_char.islower():
                result.append(" ")
            elif char.isdigit() and prev_char.isalpha():
                result.append(" ")
            elif char.isalpha() and prev_char.isdigit():
                result.append(" ")
            result.append(char.lower())
            prev_char = char
        else:
            if result and result[-1] != " ":
                result.append(" ")
            prev_char = ""
    return "".join(result).strip()


def split_mixed_label(input_str: str) -> List[str]:
    """
    将混合标签字符串按字母和数字分别切分为独立的token列表

    Args:
        input_str (str): 输入的混合标签字符串

    Returns:
        List[str]: 切分后的token列表
    """
    tokens = []
    s = input_str.lower()
    while len(s) > 0:
        if s[0] == " ":
            s = s[1:]
            continue
        match = re.match(r"[a-z]+", s)
        if match:
            tokens.append(match.group(0))
            s = s[len(match.group(0)) :]
        else:
            match = re.match(r"[0-9]+", s)
            if match:
                tokens.append(match.group(0))
                s = s[len(match.group(0)) :]
            else:
                tokens.append(s[0])
                s = s[1:]
    return tokens


def get_phoneme_seq(text: str) -> List[Phoneme]:
    """
    将文本转换为音素序列，支持中英文混合文本的音素提取

    Args:
        text (str): 输入的文本字符串

    Returns:
        List[Phoneme]: 音素对象列表
    """
    normalized = normalize_text(text)
    seq = []
    for token in split_mixed_label(normalized):
        if re.match(r"^[a-z0-9]+$", token):
            lang = "num" if token.isdigit() else "en"
            seq.append(Phoneme(token, lang, is_word_start=True, is_word_end=True))
        elif len(token) == 1:
            if not pinyin:
                seq.append(Phoneme(token, "zh", is_word_start=True, is_word_end=True))
            else:
                try:
                    pi = pinyin(token, style=Style.INITIALS, strict=False)
                    pf = pinyin(token, style=Style.FINALS, strict=False)
                    pt = pinyin(token, style=Style.TONE3, neutral_tone_with_five=True)
                    has_init = pi and pi[0] and pi[0][0]
                    if has_init:
                        seq.append(Phoneme(pi[0][0], "zh", is_word_start=True))
                    if pf and pf[0] and pf[0][0]:
                        seq.append(Phoneme(pf[0][0], "zh", is_word_start=not has_init))
                    tone = pt[0][0][-1] if pt[0][0][-1].isdigit() else "5"
                    seq.append(Phoneme(tone, "zh", is_word_end=True))
                except:
                    seq.append(
                        Phoneme(token, "zh", is_word_start=True, is_word_end=True)
                    )
        else:
            seq.append(Phoneme(token, "zh", is_word_start=True, is_word_end=True))
    return seq


def get_phoneme_info(text: str, split_char: bool = True) -> List[Phoneme]:
    """
    提取文本的详细音素信息，包括中文拼音的声母、韵母、声调等

    Args:
        text (str): 输入的文本字符串
        split_char (bool): 是否将字符拆分为单个音素单元，默认为True

    Returns:
        List[Phoneme]: 包含详细位置信息的音素对象列表
    """
    if not pinyin:
        return [
            Phoneme(c, "zh", char_start=i, char_end=i + 1) for i, c in enumerate(text)
        ]
    seq = []
    pos = 0
    while pos < len(text):
        char = text[pos]
        if "\u4e00" <= char <= "\u9fff":
            zh_start = pos
            scan_pos = pos + 1
            while scan_pos < len(text) and "\u4e00" <= text[scan_pos] <= "\u9fff":
                scan_pos += 1
            zh_end = scan_pos
            fragment = text[zh_start:zh_end]
            try:
                py_initials = pinyin(fragment, style=Style.INITIALS, strict=False)
                py_finals = pinyin(fragment, style=Style.FINALS, strict=False)
                py_tones = pinyin(
                    fragment, style=Style.TONE3, neutral_tone_with_five=True
                )
                min_len = min(
                    len(fragment), len(py_initials), len(py_finals), len(py_tones)
                )
                for i in range(min_len):
                    idx = zh_start + i
                    init, fin, tone = py_initials[i][0], py_finals[i][0], py_tones[i][0]
                    items = []
                    if init:
                        items.append(
                            Phoneme(
                                init,
                                "zh",
                                is_word_start=True,
                                char_start=idx,
                                char_end=idx + 1,
                            )
                        )
                    if fin:
                        items.append(
                            Phoneme(
                                fin,
                                "zh",
                                is_word_start=not init,
                                char_start=idx,
                                char_end=idx + 1,
                            )
                        )
                    if tone and tone[-1].isdigit():
                        items.append(
                            Phoneme(
                                tone[-1],
                                "zh",
                                is_word_end=True,
                                char_start=idx,
                                char_end=idx + 1,
                            )
                        )
                    if not items:
                        items.append(
                            Phoneme(
                                fragment[i],
                                "zh",
                                is_word_start=True,
                                is_word_end=True,
                                char_start=idx,
                                char_end=idx + 1,
                            )
                        )
                    seq.extend(items)
            except:
                for i, c in enumerate(fragment):
                    seq.append(
                        Phoneme(
                            c,
                            "zh",
                            is_word_start=True,
                            is_word_end=True,
                            char_start=zh_start + i,
                            char_end=zh_start + i + 1,
                        )
                    )
            pos = zh_end
        elif "a" <= char.lower() <= "z" or "0" <= char <= "9":
            st = pos
            pos += 1
            while pos < len(text):
                c = text[pos]
                if not ("a" <= c.lower() <= "z" or "0" <= c <= "9"):
                    break
                if (
                    (text[pos - 1].islower() and c.isupper())
                    or (text[pos - 1].isalpha() and c.isdigit())
                    or (text[pos - 1].isdigit() and c.isalpha())
                ):
                    break
                pos += 1
            tk = text[st:pos].lower()
            lang = "num" if tk.isdigit() else "en"
            if split_char:
                for i, c in enumerate(tk):
                    seq.append(
                        Phoneme(
                            c,
                            lang,
                            is_word_start=(i == 0),
                            is_word_end=(i == len(tk) - 1),
                            char_start=st + i,
                            char_end=st + i + 1,
                        )
                    )
            else:
                seq.append(
                    Phoneme(
                        tk,
                        lang,
                        is_word_start=True,
                        is_word_end=True,
                        char_start=st,
                        char_end=pos,
                    )
                )
        else:
            pos += 1
    return seq


# =============================================================================
# 2. 相似度算法 (algo_calc)
# =============================================================================

# 定义相似音素集合，用于模糊匹配
SIMILAR_PHONEMES = [
    {"an", "ang"},
    {"en", "eng"},
    {"in", "ing"},
    {"ian", "iang"},
    {"uan", "uang"},
    {"z", "zh"},
    {"c", "ch"},
    {"s", "sh"},
    {"l", "n"},
    {"f", "h"},
    {"ai", "ei"},
    {"o", "uo"},
    {"e", "ie"},
    {"p", "t"},
    {"p", "b"},
    {"t", "d"},
    {"k", "g"},
]


def _lcs_length(s1: str, s2: str) -> int:
    """
    计算两个字符串的最长公共子序列长度

    Args:
        s1: 第一个字符串
        s2: 第二个字符串

    Returns:
        最长公共子序列的长度
    """
    m, n = len(s1), len(s2)
    if m < n:
        s1, s2 = s2, s1
        m, n = n, m
    if n == 0:
        return 0
    prev = [0] * (n + 1)
    curr = [0] * (n + 1)
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            curr[j] = (
                prev[j - 1] + 1 if s1[i - 1] == s2[j - 1] else max(prev[j], curr[j - 1])
            )
        prev, curr = curr, prev
    return prev[n]


def _get_tuple_cost(t1: Tuple, t2: Tuple) -> float:
    """
    计算两个元组之间的成本

    Args:
        t1: 第一个元组
        t2: 第二个元组

    Returns:
        成本值（0.0-1.0之间）
    """
    if t1[1] != t2[1]:
        return 1.0
    if t1[0] == t2[0]:
        return 0.0
    if t1[1] == "zh":
        pair = {t1[0], t2[0]}
        for s in SIMILAR_PHONEMES:
            if pair.issubset(s):
                return 0.5
    if t1[1] == "en":
        lcs = _lcs_length(t1[0], t2[0])
        max_len = max(len(t1[0]), len(t2[0]))
        if max_len > 0:
            return 1.0 - (lcs / max_len)
    return 1.0


def fuzzy_substring_distance(hw_info: List[Tuple], input_info: List[Tuple]) -> float:
    """
    计算模糊子串距离

    Args:
        hw_info: 热词信息列表
        input_info: 输入信息列表

    Returns:
        模糊子串距离值
    """
    n, m = len(hw_info), len(input_info)
    if n == 0:
        return 0.0
    if m == 0:
        return float(n)
    prev = [0.0] * (m + 1)
    curr = [0.0] * (m + 1)
    for i in range(1, n + 1):
        curr[0] = float(i)
        for j in range(1, m + 1):
            cost = _get_tuple_cost(hw_info[i - 1], input_info[j - 1])
            curr[j] = min(prev[j] + 1.0, curr[j - 1] + 1.0, prev[j - 1] + cost)
        prev, curr = curr, prev
    return min(prev)


def fuzzy_substring_score(hw_info: List[Tuple], input_info: List[Tuple]) -> float:
    """
    计算模糊子串得分

    Args:
        hw_info: 热词信息列表
        input_info: 输入信息列表

    Returns:
        模糊子串得分值
    """
    n = len(hw_info)
    if n == 0:
        return 0.0
    return max(0.0, 1.0 - (fuzzy_substring_distance(hw_info, input_info) / n))


def fuzzy_substring_search_constrained(
    hw_info: List[Tuple], input_info: List[Tuple], threshold: float = 0.6
) -> List[Tuple[float, int, int]]:
    """
    受约束的模糊子串搜索

    Args:
        hw_info: 热词信息列表
        input_info: 输入信息列表
        threshold: 阈值，默认为0.6

    Returns:
        匹配结果列表，每个元素包含(得分, 开始位置, 结束位置)
    """
    n, m = len(hw_info), len(input_info)
    if n == 0 or m == 0:
        return []
    dp = [[float("inf")] * (m + 1) for _ in range(n + 1)]
    path = [[(0, 0)] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        if j == 0 or (j < m and input_info[j][2]):
            dp[0][j] = 0.0
            path[0][j] = (0, j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = _get_tuple_cost(hw_info[i - 1], input_info[j - 1])
            dist_match = dp[i - 1][j - 1] + cost
            dist_del = dp[i - 1][j] + 1.0
            dist_ins = dp[i][j - 1] + 1.0
            min_dist = min(dist_match, dist_del, dist_ins)
            dp[i][j] = min_dist
            if min_dist == dist_match:
                path[i][j] = path[i - 1][j - 1]
            elif min_dist == dist_del:
                path[i][j] = path[i - 1][j]
            else:
                path[i][j] = path[i][j - 1]
    results = []
    for j in range(1, m + 1):
        if not input_info[j - 1][3]:
            continue
        dist = dp[n][j]
        if dist >= n * 0.8:
            continue
        score = 1.0 - (dist / n)
        if score >= threshold:
            results.append((score, path[n][j][1], j))
    results.sort(key=lambda x: x[0], reverse=True)
    used_ends = {}
    for score, s, e in results:
        if e not in used_ends or score > used_ends[e][0]:
            used_ends[e] = (score, s, e)
    return sorted(used_ends.values(), key=lambda x: x[0], reverse=True)


# =============================================================================
# 3. RAG 加速检索 (rag_fast)
# =============================================================================
@njit(cache=True)
def _fuzzy_substring_numba(main_codes: np.ndarray, sub_codes: np.ndarray) -> float:
    n, m = len(sub_codes), len(main_codes)
    if n == 0 or m == 0:
        return float(n)
    dp = np.zeros((n + 1, m + 1), dtype=np.float32)
    for i in range(1, n + 1):
        dp[i, 0] = float(i)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0.0 if sub_codes[i - 1] == main_codes[j - 1] else 1.0
            dp[i, j] = min(
                dp[i - 1, j] + 1.0, dp[i, j - 1] + 1.0, dp[i - 1, j - 1] + cost
            )
    return float(np.min(dp[n, 1:]))


class FastRAG:
    """
    快速RAG检索类，用于加速热词检索
    """

    def __init__(self, threshold: float = 0.6):
        """
        初始化FastRAG实例

        Args:
            threshold: 阈值，默认为0.6
        """
        self.threshold = threshold
        self.ph_to_code = {}
        self.next_code = 1
        self.index = defaultdict(list)
        self.hotword_count = 0

    def _encode(self, p: str) -> int:
        """
        编码单个音素

        Args:
            p: 音素字符串

        Returns:
            编码后的整数
        """
        if p not in self.ph_to_code:
            self.ph_to_code[p] = self.next_code
            self.next_code += 1
        return self.ph_to_code[p]

    def _encode_seq(self, phs: List[str]) -> np.ndarray:
        """
        编码音素序列

        Args:
            phs: 音素列表

        Returns:
            编码后的数组
        """
        return np.array([self._encode(p) for p in phs], dtype=np.int32)

    def add_hotwords(self, hotwords: Dict[str, List[Phoneme]]):
        """
        添加热词到索引中

        Args:
            hotwords: 热词字典，键为热词，值为音素列表
        """
        for hw, phs in hotwords.items():
            if not phs:
                continue
            codes = self._encode_seq([p.value for p in phs])
            # 统一索引前两个音素（中文：声母+韵母，英文：前两位容错）
            indices = list(range(min(len(codes), 2)))
            for i in indices:
                self.index[codes[i]].append((hw, codes))
            self.hotword_count += 1

    def search(
        self, input_phs: List[Phoneme], top_k: int = 10
    ) -> List[Tuple[str, float]]:
        """
        搜索匹配的热词

        Args:
            input_phs: 输入音素列表
            top_k: 返回前k个结果，默认为10

        Returns:
            匹配结果列表，每个元素包含(热词, 得分)
        """
        if not input_phs:
            return []

        # 获取完整的输入音素编码序列（保持顺序）
        input_codes_seq = self._encode_seq([p.value for p in input_phs])

        # 为了索引查找，我们还需要输入音素编码集合（包括相似音素）
        input_codes_set = set(input_codes_seq)

        # 添加相似音素
        for p in input_phs:
            val = p.value
            if p.lang != "zh":
                continue
            for s_set in SIMILAR_PHONEMES:
                if val not in s_set:
                    continue
                for sim_val in s_set:
                    sim_code = self.ph_to_code.get(sim_val)
                    if sim_code is not None:
                        input_codes_set.add(sim_code)

        # 收集候选
        candidates = []
        seen = set()
        for c in input_codes_set:
            for hw, codes in self.index.get(c, []):
                if hw in seen:
                    continue
                candidates.append((hw, codes))
                seen.add(hw)

        # 使用完整的输入序列进行搜索
        results = []
        for hw, h_codes in candidates:
            if len(h_codes) > len(input_codes_seq) + 3:
                continue
            # 使用完整的输入序列进行匹配
            dist = _fuzzy_substring_numba(input_codes_seq, h_codes)
            score = 1.0 - (dist / len(h_codes))
            if score >= self.threshold:
                results.append((hw, round(score, 3)))
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _python_dist(self, main, sub):
        """
        Python实现的距离计算

        Args:
            main: 主序列
            sub: 子序列

        Returns:
            距离值
        """
        n, m = len(sub), len(main)
        dp = [[0.0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            dp[i][0] = float(i)
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost = 0.0 if sub[i - 1] == main[j - 1] else 1.0
                dp[i][j] = min(
                    dp[i - 1][j] + 1.0, dp[i][j - 1] + 1.0, dp[i - 1][j - 1] + cost
                )
        return min(dp[n][1:])


# =============================================================================
# 4. 纠错系统逻辑 (hot_phoneme & hot_rectification)
# =============================================================================


class MatchResult(NamedTuple):
    """
    匹配结果命名元组
    """

    start: int  # 匹配开始位置
    end: int  # 匹配结束位置
    score: float  # 匹配得分
    hotword: str  # 匹配的热词


class CorrectionResult(NamedTuple):
    """
    纠正结果命名元组
    """

    text: str  # 纠正后的文本
    matchs: List[Tuple[str, str, float]]  # 匹配列表
    similars: List[Tuple[str, str, float]]  # 相似列表


class PhonemeCorrector:
    """
    音素纠正器类，用于处理文本中的音素错误
    """

    def __init__(self, threshold: float = 0.7, similar_threshold: float = None):
        """
        初始化音素纠正器

        Args:
            threshold: 主要阈值，默认为0.7
            similar_threshold: 相似阈值，默认为None
        """
        self.threshold = threshold
        self.similar_threshold = (
            similar_threshold if similar_threshold is not None else threshold - 0.2
        )
        self.hotwords: Dict[str, List[Phoneme]] = {}
        self.fast_rag = FastRAG(
            threshold=min(self.threshold, self.similar_threshold) - 0.1
        )
        self._lock = threading.Lock()

    def clear_hotwords(self) -> Tuple[int, int]:
        """
        清空所有热词

        Returns:
            int: 清空后剩余的热词数量（应该总是返回0）
            int: 清空的热词数量
        """
        with self._lock:
            count = len(self.hotwords)
            self.hotwords.clear()
            # 同时重建FastRAG索引为空
            self.fast_rag = FastRAG(
                threshold=min(self.threshold, self.similar_threshold) - 0.1
            )

        return len(self.hotwords), count

    def update_hotwords(self, text: str, append_mode: bool = False) -> int:
        """
        更新热词列表

        Args:
            text: 包含热词的文本
            append_mode: 是否追加模式，默认为False（覆盖模式）

        Returns:
            新增热词数量
        """
        lines = [
            l.strip()
            for l in text.splitlines()
            if l.strip() and not l.strip().startswith("#")
        ]
        new_hw = {}
        for hw in lines:
            phs = get_phoneme_info(hw)
            if phs:
                new_hw[hw] = phs
            else:
                logger.warning(f"未获取到热词 {hw} 的因素信息")

        with self._lock:
            if append_mode:
                # 追加模式：合并新热词到现有热词
                self.hotwords.update(new_hw)
                # 只向现有 FastRAG 索引添加新热词，不重置
                now = time.time()
                self.fast_rag.add_hotwords(new_hw)  # 只添加新热词
                logger.trace(f"向fast_rag索引添加新热词耗时：{time.time() - now:.5f}秒")
            else:
                # 覆盖模式：替换整个热词字典
                self.hotwords = new_hw
                # 重建fast_rag索引
                self.fast_rag = FastRAG(
                    threshold=min(self.threshold, self.similar_threshold) - 0.1
                )
                now = time.time()
                self.fast_rag.add_hotwords(self.hotwords)
                logger.trace(f"重建fast_rag索引耗时：{time.time() - now:.5f}秒")

        return len(new_hw)

    def load_hotwords_file(self, path: Path, append_mode: bool = False) -> int:
        """
        从文件加载热词

        Args:
            path: 文件路径
            append_mode: 是否追加模式，默认为False（覆盖模式）

        Returns:
            加载的热词数量
        """
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return self.update_hotwords(f.read(), append_mode=append_mode)
        else:
            logger.warning(f"热词文件不存在：{path}")
            return 0

    def _find_matches(self, text, fast_results, input_processed):
        """
        查找匹配项

        Args:
            text: 原始文本
            fast_results: 快速搜索结果
            input_processed: 处理后的输入

        Returns:
            匹配列表和相似列表
        """
        matches, similars = [], []
        search_thresh = min(self.threshold, self.similar_threshold) - 0.1
        for hw, _ in fast_results:
            hw_phs = self.hotwords[hw]
            hw_compare = [p.info[:5] for p in hw_phs]
            found = fuzzy_substring_search_constrained(
                hw_compare, input_processed, threshold=search_thresh
            )
            for score, s_idx, e_idx in found:
                char_st, char_ed = (
                    input_processed[s_idx][5],
                    input_processed[e_idx - 1][6],
                )
                res = MatchResult(char_st, char_ed, score, hw)
                if score >= self.threshold:
                    matches.append(res)
                if score >= self.similar_threshold:
                    similars.append((text[char_st:char_ed], hw, score))
        similars.sort(key=lambda x: (x[2], len(x[1])), reverse=True)
        final_sims, seen = [], set()
        for o, hw, s in similars:
            if hw not in seen:
                final_sims.append((o, hw, s))
                seen.add(hw)
        return matches, final_sims

    def _resolve_and_replace(self, text, matches):
        """
        解析并替换匹配项

        Args:
            text: 原始文本
            matches: 匹配列表

        Returns:
            替换后的文本和最终匹配列表
        """
        matches.sort(key=lambda x: (x.score, x.end - x.start), reverse=True)
        final_m, occupied = [], []
        for m in matches:
            if any(not (m.end <= rs or m.start >= re) for rs, re in occupied):
                continue
            if text[m.start : m.end] != m.hotword:
                final_m.append(m)
            occupied.append((m.start, m.end))
        res = list(text)
        final_m.sort(key=lambda x: x.start, reverse=True)
        for m in final_m:
            res[m.start : m.end] = list(m.hotword)
        return "".join(res), [
            (text[m.start : m.end], m.hotword, m.score)
            for m in sorted(final_m, key=lambda x: x.start)
        ]

    def correct(self, text, k=10):
        """
        对文本进行纠正

        Args:
            text: 待纠正的文本
            k: 返回结果数量，默认为10

        Returns:
            纠正结果对象
        """
        in_phs = get_phoneme_info(text)
        if not in_phs or not self.hotwords:
            return CorrectionResult(text, [], [])
        with self._lock:
            fast_res = self.fast_rag.search(in_phs, top_k=100)
            processed = [p.info for p in in_phs]
            matches, sims = self._find_matches(text, fast_res, processed)
        nt, fhw = self._resolve_and_replace(text, matches)
        return CorrectionResult(nt, fhw, sims[:k])


def _get_word_boundaries(text: str) -> List[Tuple[int, int, str]]:
    """
    获取单词边界

    Args:
        text: 输入文本

    Returns:
        边界列表，每个元素包含(开始位置, 结束位置, 单词)
    """
    bounds, i, n = [], 0, len(text)
    while i < n:
        if not (text[i].isalnum() or "\u4e00" <= text[i] <= "\u9fff"):
            i += 1
            continue
        s = i
        if "\u4e00" <= text[i] <= "\u9fff":
            i += 1
        else:
            low = text[i].islower()
            while i < n and text[i].isalnum():
                if text[i].isupper() and low and i > s:
                    break
                low = text[i].islower()
                i += 1
        bounds.append((s, i, text[s:i]))
    return bounds


def extract_diff_fragments(wrong: str, right: str) -> List[str]:
    """
    提取差异片段

    Args:
        wrong: 错误文本
        right: 正确文本

    Returns:
        差异片段列表
    """
    wb, rb = _get_word_boundaries(wrong), _get_word_boundaries(right)
    matcher = SequenceMatcher(None, [b[2] for b in wb], [b[2] for b in rb])
    frags = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ("replace", "delete") and i2 > i1:
            frags.append(wrong[wb[i1][0] : wb[i2 - 1][1]])
        if tag in ("replace", "insert") and j2 > j1:
            frags.append(right[rb[j1][0] : rb[j2 - 1][1]])
    return list(dict.fromkeys(frags))


# =============================================================================
# 5. 调试工具 (Phoneme Debug)
# =============================================================================


def get_phoneme_cost(p1: Phoneme, p2: Phoneme) -> float:
    """
    获取两个音素之间的成本

    Args:
        p1: 第一个音素
        p2: 第二个音素

    Returns:
        成本值（0.0-1.0之间）
    """
    if p1.lang != p2.lang:
        return 1.0
    if p1.value == p2.value:
        return 0.0
    if p1.lang == "zh" and p2.lang == "zh":
        pair = {p1.value, p2.value}
        for s in SIMILAR_PHONEMES:
            if pair.issubset(s):
                return 0.5
    if p1.lang == "en" and p2.lang == "en":
        lcs_len = _lcs_length(p1.value, p2.value)
        max_len = max(len(p1.value), len(p2.value))
        return 1.0 - (lcs_len / max_len)
    return 1.0


def find_best_match(
    main_seq: List[Phoneme], sub_seq: List[Phoneme]
) -> Tuple[float, int, int]:
    """
    查找最佳匹配

    Args:
        main_seq: 主序列
        sub_seq: 子序列

    Returns:
        匹配结果元组(得分, 开始位置, 结束位置)
    """
    n, m = len(sub_seq), len(main_seq)
    if n == 0 or m == 0:
        return 0.0, 0, 0
    valid_starts = [j for j in range(m) if main_seq[j].is_word_start]
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for j in range(m + 1):
        if j not in valid_starts:
            dp[0][j] = float("inf")
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + 1.0
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = get_phoneme_cost(sub_seq[i - 1], main_seq[j - 1])
            dp[i][j] = min(
                dp[i - 1][j] + 1.0, dp[i][j - 1] + 1.0, dp[i - 1][j - 1] + cost
            )
    min_dist, end_pos, best_start = float("inf"), 0, 0
    for j in range(1, m + 1):
        if dp[n][j] < min_dist:
            curr_i, curr_j = n, j
            while curr_i > 0:
                cost = get_phoneme_cost(sub_seq[curr_i - 1], main_seq[curr_j - 1])
                if (
                    curr_j > 0
                    and abs(dp[curr_i][curr_j] - (dp[curr_i - 1][curr_j - 1] + cost))
                    < 1e-9
                ):
                    curr_i -= 1
                    curr_j -= 1
                elif abs(dp[curr_i][curr_j] - (dp[curr_i - 1][curr_j] + 1.0)) < 1e-9:
                    curr_i -= 1
                elif (
                    curr_j > 0
                    and abs(dp[curr_i][curr_j] - (dp[curr_i][curr_j - 1] + 1.0)) < 1e-9
                ):
                    curr_j -= 1
                else:
                    curr_i -= 1
            if curr_j in valid_starts:
                min_dist = dp[n][j]
                end_pos = j
                best_start = curr_j
    return 1.0 - (min_dist / n), best_start, end_pos


def 热词替换(句子, debug: bool = False, logger: Optional[Logger] = None):
    """
    从热词词典中查找匹配的热词，替换句子

    句子：       被查找和替换的句子
    debug:       是否进行调试
    """
    _logger = logger if logger is not None else default_logger
    from util.client.cosmic import Cosmic, console

    now = time.time()
    result = Cosmic.corrector.correct(句子)
    dur = time.time() - now

    if debug and (result.matchs or result.similars):
        if result.matchs:
            for wrong, right, score in result.matchs:
                console.print(
                    f"hot_sub_rag Result: [{score_to_color(score)}]{wrong} -> {right} [/]    Score: {score:.2f}    Duration: {dur:.2f}s"
                )
                _logger.debug(
                    f"hot_sub_rag Result: {wrong} -> {right}    Score: {score:.2f}    Duration: {dur:.2f}s"
                )

        if result.similars:
            # 创建已匹配热词的集合
            matched_words = (
                {right for _, right, _ in result.matchs} if result.matchs else set()
            )

            # 过滤掉已匹配的潜在热词
            filtered_similars = [
                (w, r, s) for w, r, s in result.similars if r not in matched_words
            ]
            if filtered_similars:
                for original, potential, score in filtered_similars:
                    console.print(
                        f"hot_sub_rag Potential: [{score_to_color(score)}]{original} -> {potential} [/]    Score: {score:.2f}"
                    )
                    _logger.debug(
                        f"hot_sub_rag Potential: {original} -> {potential}    Score: {score:.2f}"
                    )

    return result.text


def score_to_color(score: float) -> str:
    """将分数转换为颜色"""
    colors = [
        "#ff6161",
        "#ff9999",
        "#ffb3b3",
        "#ffcc99",
        "#ffdb99",
        "#ffe699",
        "#ffffcc",
        "#e6f2cc",
        "#b3d9b3",
        "#74c074",
    ]

    return colors[min(int(score * 10), 9)]


if __name__ == "__main__":
    # =============================================================================
    # 7. 数据准备与主流演示
    # =============================================================================

    # --- A. 数据准备 ---
    hotwords_data = """
    Claude
    Bilibili
    Microsoft
    麦当劳
    肯德基
    VsCode
    七浦路
    """

    cases = [
        "我想去吃买当劳和肯得鸡",
        "喜欢刷Bili Bili",
        "我很喜欢 cloud",
        "我家哥哥在齐铺路",
    ]

    # --- B. 系统初始化 ---
    corrector = PhonemeCorrector(threshold=0.7)

    # 尝试加载外部文件 (如果存在)
    txt_paths: list[Path] = [
        # Path("hot-rag.txt"),
        Path("hot-zh.txt"),
        Path("hot-en.txt"),
    ]
    for txt_path in txt_paths:
        now = time.time()
        新增热词数量: int = corrector.load_hotwords_file(txt_path, append_mode=True)
        logger.trace(
            f"已从外部文件 {txt_path} 加载 {新增热词数量} 个热词，总计 {len(corrector.hotwords)} 个热词，耗时 {time.time() - now:.5f} 秒"
        )

    # 追加演示数据
    新增热词数量: int = corrector.update_hotwords(hotwords_data, append_mode=True)
    logger.trace(f"已追加 {新增热词数量} 个热词，总计 {len(corrector.hotwords)} 个热词")

    def format_score_with_gradient_bar(score: float) -> str:
        """创建进度条"""
        bar_length = 15
        filled = int(score * bar_length)
        color = score_to_color(score)

        # 创建进度条
        bar = f"[{color}]{'█' * filled}[/{color}][grey85]{'░' * (bar_length - filled)}[/grey85]"
        return bar

    # --- C. 执行综合纠错演示 ---
    def 综合纠错演示():
        console.print(
            Rule(
                "[bold red]CapsWriter-Offline 综合纠错系统演示[/bold red]",
                characters="=",
                style="bold red",
            )
        )
        for i, t in enumerate(cases, start=1):
            result = corrector.correct(t)

            result_table = Table(
                expand=True,
                box=box.ROUNDED,
                header_style="bold blue",
                title_style="bold yellow",
                padding=(0, 0),
            )
            result_table.add_column("项目", width=8, no_wrap=True)
            result_table.add_column(
                "内容",
                overflow="fold",
                no_wrap=False,
                ratio=True,
            )
            result_table.add_row("原文", t)
            result_table.add_row("纠错后", result.text, style="green")

            console.print(
                "\n", Rule(f"[bold red]Case {i}.[/]", style="bold red", align="left")
            )
            console.print(result_table)

            if result.matchs:
                matches_table = Table(
                    title="[bold green]匹配热词[/bold green]",
                    show_header=True,
                    title_justify="left",
                    expand=True,
                    box=box.SIMPLE,
                    header_style="bold blue",
                    padding=(0, 0),
                )
                matches_table.add_column("项目", width=8, no_wrap=True)
                matches_table.add_column(
                    "内容",
                    overflow="fold",
                    no_wrap=False,
                    ratio=True,
                )

                for wrong, right, score in result.matchs:
                    matches_table.add_row("原文片段", wrong)
                    matches_table.add_row(
                        "匹配热词", right, style=score_to_color(score)
                    )
                    matches_table.add_row(
                        "相似度", f"{format_score_with_gradient_bar(score)} {score:.4f}"
                    )
                    matches_table.add_section()

                console.print(matches_table)

            if result.similars:
                # 创建已匹配热词的集合
                matched_words = (
                    {right for _, right, _ in result.matchs} if result.matchs else set()
                )

                # 过滤掉已匹配的潜在热词
                filtered_similars = [
                    (w, r, s) for w, r, s in result.similars if r not in matched_words
                ]

                if filtered_similars:
                    similars_table = Table(
                        title="[bold yellow]潜在热词[/bold yellow]",
                        show_header=True,
                        title_justify="left",
                        expand=True,
                        box=box.SIMPLE,
                        header_style="bold blue",
                        padding=(0, 0),
                    )

                    similars_table.add_column("项目", width=8, no_wrap=True)
                    similars_table.add_column(
                        "内容",
                        overflow="fold",
                        no_wrap=False,
                        ratio=True,
                    )

                    for wrong, right, score in filtered_similars:
                        similars_table.add_row("原文片段", wrong)
                        similars_table.add_row(
                            "潜在热词", right, style=score_to_color(score)
                        )
                        similars_table.add_row(
                            "相似度",
                            f"{format_score_with_gradient_bar(score)} {score:.4f}",
                        )
                        similars_table.add_section()

                    console.print(similars_table)

            console.print(Rule(style="bold red"))

        console.print(
            Rule(
                characters="=",
                style="bold red",
            )
        )

    # --- D. 音素匹配调试演示 ---
    def 音素匹配调试演示():
        def test_pair(input_text, hotword, split_char=True):
            """
            测试输入文本与热词的匹配

            Args:
                input_text: 输入文本
                hotword: 热词
                split_char: 是否分割字符，默认为True
            """
            console.print(
                "\n",
                Rule(
                    f"[bold red]Testing: '{input_text}' vs '{hotword}'[/]",
                    style="bold red",
                    align="left",
                ),
            )
            input_seq = get_phoneme_info(input_text, split_char=split_char)
            target_seq = get_phoneme_info(hotword, split_char=split_char)
            score, start, end = find_best_match(input_seq, target_seq)
            pair_table = Table(
                title=f"[{score_to_color(score)}]相似度：{score:.4f}[/]",
                show_header=True,
                title_justify="left",
                expand=True,
                box=box.SIMPLE,
                header_style="bold blue",
                padding=(0, 0),
            )
            pair_table.add_column("项目", width=15, no_wrap=True)
            pair_table.add_column(
                "内容",
                overflow="fold",
                no_wrap=False,
                ratio=True,
            )
            pair_table.add_row("Input Seq:", f"{[p.value for p in input_seq]}")
            pair_table.add_row("Target Seq:", f"{[p.value for p in target_seq]}")
            pair_table.add_row(
                "Score:",
                f"{format_score_with_gradient_bar(score)} {score:.4f}",
            )
            if score > 0:
                matched_segment = input_seq[start:end]
                pair_table.add_row(
                    "Matched Segment:",
                    f"{[p.value for p in matched_segment]}",
                )

            console.print(pair_table)
            console.print(Rule(style="bold red"))

        console.print(
            "\n\n",
            Rule(
                "[bold red]Phoneme Debug 调试演示[/]",
                characters="=",
                style="bold red",
            ),
        )
        pair_data: list[tuple[str, str]] = [
            ("cloud", "claude"),
            ("vscode", "VS Code"),
            ("七福路", "七浦路"),
            ("拓维信息", "破为信息"),
        ]
        for input_text, hotword in pair_data:
            test_pair(input_text, hotword)

        console.print(
            Rule(
                characters="=",
                style="bold red",
            )
        )

    def 调用示例():
        import sys

        sys.path.append("..")
        from util.client.cosmic import Cosmic

        Cosmic.corrector.load_hotwords_file(Path("hot-zh.txt"), append_mode=False)
        Cosmic.corrector.load_hotwords_file(Path("hot-en.txt"), append_mode=True)

        print(热词替换("我家哥哥在齐铺路", debug=True))

    # 综合纠错演示()
    # 音素匹配调试演示()
    调用示例()
