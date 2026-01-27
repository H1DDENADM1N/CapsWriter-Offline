# coding: utf-8
"""
高性能 RAG 加速模块
"""

from collections import defaultdict
from typing import Any, Dict, List, Tuple

import loguru
import numpy as np

# 尝试导入 Numba
try:
    import numba
    from numba import jit, njit

    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False

# 使用模块变量 _logger，允许外部注入
_logger = loguru.logger


def set_rag_logger(logger_instance: Any):
    """外部调用此函数注入 logger，用于多进程日志"""
    global _logger
    _logger = logger_instance


# =============================================================================
# Numba 加速版本
# =============================================================================

if HAS_NUMBA:

    @njit(cache=False)  # 禁用缓存以避免导入路径问题
    def _fuzzy_substring_distance_numba(
        main_codes: np.ndarray, sub_codes: np.ndarray
    ) -> float:
        """
        Numba 加速的模糊子串距离计算

        使用整数编码代替字符串，大幅提升性能。
        """
        n = len(sub_codes)
        m = len(main_codes)

        if n == 0 or m == 0:
            return float(n)

        dp = np.zeros((n + 1, m + 1), dtype=np.float32)

        for i in range(1, n + 1):
            dp[i, 0] = float(i)

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                if sub_codes[i - 1] == main_codes[j - 1]:
                    cost = 0.0
                else:
                    cost = 1.0

                dp[i, j] = min(
                    dp[i - 1, j] + 1.0,  # 删除
                    dp[i, j - 1] + 1.0,  # 插入
                    dp[i - 1, j - 1] + cost,  # 替换/匹配
                )

        min_dist = dp[n, 1]
        for j in range(2, m + 1):
            if dp[n, j] < min_dist:
                min_dist = dp[n, j]

        return min_dist


# =============================================================================
# 音素编码器（字符串 -> 整数）
# =============================================================================

from .algo_calc import SIMILAR_PHONEMES
from .algo_phoneme import Phoneme


class PhonemeEncoder:
    """将音素字符串编码为整数，用于 Numba 加速"""

    def __init__(self):
        self.phoneme_to_code: Dict[str, int] = {}
        self.code_to_phoneme: Dict[int, str] = {}
        self.next_code = 1  # 0 保留

    def encode(self, phoneme: str) -> int:
        if phoneme not in self.phoneme_to_code:
            self.phoneme_to_code[phoneme] = self.next_code
            self.code_to_phoneme[self.next_code] = phoneme
            self.next_code += 1
        return self.phoneme_to_code[phoneme]

    def encode_sequence(self, phonemes: List[str]) -> np.ndarray:
        return np.array([self.encode(p) for p in phonemes], dtype=np.int32)


# =============================================================================
# 倒排索引
# =============================================================================


class PhonemeIndex:
    """
    多音素倒排索引

    按热词前几个音素分桶，检索时只匹配音素在输入中出现过的热词，减少计算量。
    - 中文：索引前两个音素（声母+韵母，即第一个字的完整拼音）
    - 英文：索引前两个音素（容错首音素识别错误，如 klaude -> Claude）
    """

    def __init__(self):
        self.encoder = PhonemeEncoder()
        self.index: Dict[int, List[Tuple[str, np.ndarray]]] = defaultdict(list)
        self.all_hotwords: List[Tuple[str, np.ndarray]] = []

    def add(self, hotword: str, phonemes: List[Phoneme]):
        if not phonemes:
            return

        phoneme_strs = [p.value for p in phonemes]
        codes = self.encoder.encode_sequence(phoneme_strs)

        limit = min(len(codes), 2)
        indices = list(range(limit))

        target_codes = {codes[i] for i in indices if i < len(codes)}

        for code in target_codes:
            self.index[code].append((hotword, codes))

        self.all_hotwords.append((hotword, codes))

    def get_candidates(
        self, input_phonemes: List[Phoneme]
    ) -> List[Tuple[str, np.ndarray]]:
        input_codes = set()

        for p in input_phonemes:
            val = p.value
            code = self.encoder.phoneme_to_code.get(val)
            if code is not None:
                input_codes.add(code)

            if p.lang != "zh":
                continue

            for s_set in SIMILAR_PHONEMES:
                if val not in s_set:
                    continue
                for sim_val in s_set:
                    sim_code = self.encoder.phoneme_to_code.get(sim_val)
                    if sim_code is None:
                        continue
                    input_codes.add(sim_code)

        candidates = []
        seen = set()
        for code in input_codes:
            for hw, codes in self.index.get(code, []):
                if hw in seen:
                    continue
                candidates.append((hw, codes))
                seen.add(hw)

        return candidates

    def encode_input(self, phonemes: List[Phoneme]) -> np.ndarray:
        phoneme_strs = [p.value for p in phonemes]
        return self.encoder.encode_sequence(phoneme_strs)


# =============================================================================
# 高性能 RAG 检索器
# =============================================================================


class FastRAG:
    """
    高性能 RAG 检索器

    特点：
    1. Numba JIT 加速核心算法
    2. 首音素倒排索引减少候选
    3. 长度过滤跳过不可能匹配
    """

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold
        self.index = PhonemeIndex()
        self.hotword_count = 0

    def add_hotwords(self, hotwords: Dict[str, List[Phoneme]]):
        for hw, phonemes in hotwords.items():
            if phonemes:
                self.index.add(hw, phonemes)
                self.hotword_count += 1

    def search(
        self, input_phonemes: List[Phoneme], top_k: int = 10
    ) -> List[Tuple[str, float]]:
        """
        检索相关热词（高层编排）
        """
        if not input_phonemes:
            return []

        # 使用 _logger
        _logger.debug(
            f"[DEBUG] FastRAG.search: input_phonemes type={type(input_phonemes)}, len={len(input_phonemes)}"
        )
        if input_phonemes:
            _logger.debug(
                f"[DEBUG] FastRAG.search: input_phonemes[0] type={type(input_phonemes[0])}, value={input_phonemes[0]}"
            )

        input_codes = self.index.encode_input(input_phonemes)
        candidates = self.index.get_candidates(input_phonemes)

        results = self._score_candidates(input_codes, candidates)

        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _score_candidates(
        self, input_codes: np.ndarray, candidates: List[Tuple[str, np.ndarray]]
    ) -> List[Tuple[str, float]]:
        """对候选列表进行相似度计算与阈值过滤"""
        results = []
        input_len = len(input_codes)

        for hw, hw_codes in candidates:
            hw_len = len(hw_codes)

            if hw_len > input_len + 3:
                continue

            if HAS_NUMBA:
                min_dist = _fuzzy_substring_distance_numba(input_codes, hw_codes)
            else:
                min_dist = self._python_distance(input_codes, hw_codes)

            score = 1.0 - (min_dist / hw_len)
            if score >= self.threshold:
                results.append((hw, round(score, 3)))
        return results

    def compute_score(
        self, input_phonemes: List[str], hotword_phonemes: List[str]
    ) -> float:
        """
        计算单个热词的精确分数 (用于重排序)
        """
        input_codes = self.index.encode_input(input_phonemes)
        hw_codes = self.index.encode_input(hotword_phonemes)

        hw_len = len(hw_codes)
        if hw_len == 0:
            return 0.0

        if HAS_NUMBA:
            min_dist = _fuzzy_substring_distance_numba(input_codes, hw_codes)
        else:
            min_dist = self._python_distance(input_codes, hw_codes)

        return max(0.0, 1.0 - (min_dist / hw_len))

    def _python_distance(self, main_codes: np.ndarray, sub_codes: np.ndarray) -> float:
        """纯 Python 版本（Numba 不可用时）"""
        n = len(sub_codes)
        m = len(main_codes)

        if n == 0 or m == 0:
            return float(n)

        dp = [[0.0] * (m + 1) for _ in range(n + 1)]

        for i in range(1, n + 1):
            dp[i][0] = float(i)

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost = 0.0 if sub_codes[i - 1] == main_codes[j - 1] else 1.0
                dp[i][j] = min(
                    dp[i - 1][j] + 1.0, dp[i][j - 1] + 1.0, dp[i - 1][j - 1] + cost
                )

        return min(dp[n][j] for j in range(1, m + 1))
