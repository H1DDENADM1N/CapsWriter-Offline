# coding: utf-8
"""
Qwen 解码器 GGUF 的 token embedding「按需取行」读取器

用途：LLM 二遍解码要把 ChatML 提示拼成 embedding 批次送进 ``decode_embd``，
需要按 token id 拿到 float32 行。

为什么按行取而不是整表反量化
------------------------------------------------
``token_embd.weight`` 在 1.7B 解码器里是 Q4_K、``[2048, 151936]``；整表反量化
成 float32 要 ::

    151936 * 2048 * 4 B ≈ 1.24 GB

而一次二遍解码的提示只有十几到几百个 token。所以这里只在真正被请求时反量化
对应行，并按 id 放一个 LRU（默认 4096 条 ≈ 33 MB 上限），命中就不再算。

本机 ``gguf`` 版本（0.19.x）的两个坑
------------------------------------------------
    - ``GGUFReader.tensors`` 是 **list**，``get_tensor()`` 只接受整数索引，
      传张量名会 ``TypeError: list indices must be integers``；取张量必须写
      ``next(t for t in reader.tensors if t.name == "token_embd.weight")``。
    - 反量化走 ``gguf.quants.dequantize(data, tensor_type)``，对 Q4_K 内部派发到
      ``Q4_K.dequantize``。输入是形状 ``(n_rows, blocks_per_row * type_size)``
      的 uint8 视图（Q4_K：block_size=256、type_size=144），2 行 2048 维就是
      ``(2, 1152)``，一次调用拿到 ``(2, 2048)``。

GGUF 里 ``token_embd.weight`` 的 ``shape`` 是 ``[n_embd, n_vocab]``，但数据是
行主序、外层行就是 vocab，所以 **id 直接当行号**用（``data[id]``），不要按
``shape`` 去理解第二个维度。

可选整表缓存
------------------------------------------------
``<gguf>.embd.npy`` 存在且形状/dtype 与模型匹配时直接 ``mmap`` 读，比按行反
量化更省 CPU（代价是 1.24 GB 磁盘）。**写入是显式 opt-in**（``write_cache()``），
不在构造或首次 ``rows()`` 时偷偷落盘 —— 计划里的措辞是「写入不强制，读优先」，
而给每个装了模型的目录凭空多写 1.24 GB 不是读路径该有的副作用。
"""

from __future__ import annotations

import logging
import operator
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Sequence

import numpy as np

import gguf
from gguf.quants import dequantize

__all__ = ["TokenEmbedding", "EMBED_TENSOR", "LRU_MAX", "CACHE_SUFFIX"]

logger = logging.getLogger(__name__)

#: 解码器里 token embedding 张量的名字
EMBED_TENSOR = "token_embd.weight"

#: 按 id 缓存的行数上限（4096 × 2048 float32 ≈ 33 MB）
LRU_MAX = 4096

#: 整表缓存相对 GGUF 的文件名后缀
CACHE_SUFFIX = ".embd.npy"

#: write_cache() 每次反量化的行数（8192 × 2048 float32 ≈ 67 MB 峰值）
_WRITE_CHUNK_ROWS = 8192


class TokenEmbedding:
    """
    解码器 GGUF 的 token embedding 按行读取器

    Args:
        gguf_path: 解码器 GGUF 路径（含 ``token_embd.weight``）
        cache: 是否启用整表缓存 ``<gguf>.embd.npy`` 的 mmap 复用（只影响读路径，
            ``write_cache()`` 始终可显式调用）

    Note:
        必须最后调用 :meth:`close`（LLM 解码器里的顺序是 ``Context`` → ``Model``
        → ``TokenEmbedding``）。Windows 上 GGUF 是 mmap 打开的，不关会一直占着
        模型文件的锁。
    """

    def __init__(self, gguf_path: str | Path, cache: bool = True):
        self.path = Path(gguf_path)
        if not self.path.is_file():
            raise FileNotFoundError(f"解码器 GGUF 不存在: {self.path}")

        self._lock = threading.Lock()
        self._lru: "OrderedDict[int, np.ndarray]" = OrderedDict()
        self._closed = False
        self._mmap: np.ndarray | None = None

        self._reader = gguf.GGUFReader(str(self.path))
        tensor = next((t for t in self._reader.tensors if t.name == EMBED_TENSOR), None)
        if tensor is None:
            names = ", ".join(t.name for t in self._reader.tensors[:8])
            self.close()
            raise KeyError(f"{self.path.name} 里没有 {EMBED_TENSOR}；前几个张量: {names}")

        self._tensor = tensor
        if len(tensor.shape) != 2:
            self.close()
            raise ValueError(f"{EMBED_TENSOR} 应为二维 [n_embd, n_vocab]，实际 {tensor.shape}")
        # GGUF 的 shape 是 [n_embd, n_vocab]，数据行是 vocab
        self.n_embd = int(tensor.shape[0])
        self.n_vocab = int(tensor.shape[1])
        self._data = np.asarray(tensor.data)
        if self._data.shape[:1] != (self.n_vocab,):
            self.close()
            raise ValueError(
                f"{EMBED_TENSOR} 的数据行数 {self._data.shape[0]} 与 n_vocab "
                f"{self.n_vocab} 不一致（shape={tensor.shape}），无法按 id 取行"
            )

        self.cache_path = self.path.with_name(self.path.name + CACHE_SUFFIX)
        if cache:
            self._mmap = self._open_cache()

    # -- 只读属性 ---------------------------------------------------------

    @property
    def using_cache_file(self) -> bool:
        """当前是否在走 ``<gguf>.embd.npy`` 的 mmap 读路径"""
        return self._mmap is not None

    @property
    def cached_rows(self) -> int:
        """LRU 里当前缓存的行数"""
        return len(self._lru)

    # -- 取行 -------------------------------------------------------------

    def rows(self, ids: Sequence[int]) -> np.ndarray:
        """
        按 token id 取出 embedding 行

        Args:
            ids: token id 序列（可重复；顺序即返回顺序）

        Returns:
            ``[len(ids), n_embd]`` 的 float32 数组；``ids`` 为空时返回 ``[0, n_embd]``

        Raises:
            RuntimeError: 已 ``close()``
            IndexError: id 越界
            TypeError: id 不是整数
        """
        if self._closed:
            raise RuntimeError("TokenEmbedding 已关闭，不能再取行")

        id_list = [self._as_id(i) for i in ids]
        if not id_list:
            return np.zeros((0, self.n_embd), np.float32)

        if self._mmap is not None:
            # mmap 整表：直接花式索引，numpy 自动返回同形状的 float32 新数组
            return np.asarray(self._mmap[id_list], dtype=np.float32)

        with self._lock:
            uniq = list(dict.fromkeys(id_list))
            missing = [i for i in uniq if i not in self._lru]
            fresh = self._dequantize(missing) if missing else None

            # 先按请求顺序（含重复）组装，再更新 LRU —— 反过来的话，
            # 一次请求超过 LRU_MAX 行时早期行已被淘汰，组装阶段会 KeyError。
            out = np.empty((len(id_list), self.n_embd), np.float32)
            if fresh is None:
                for k, i in enumerate(id_list):
                    out[k] = self._lru[i]
            else:
                rows_of = dict(zip(missing, fresh))
                for k, i in enumerate(id_list):
                    out[k] = self._lru[i] if i not in rows_of else rows_of[i]
                # 只把「最近请求的 LRU_MAX 行」留在缓存里，避免超大请求把内存吃满
                keep = missing[-LRU_MAX:] if len(missing) > LRU_MAX else missing
                if keep is not missing:
                    rows_of = {i: rows_of[i] for i in keep}
                for i, vec in rows_of.items():
                    # copy 一行：否则缓存会一直引用整个批次的基数组
                    self._lru[i] = np.array(vec, dtype=np.float32, copy=True)
                    self._lru.move_to_end(i)
            for i in uniq:
                if i in self._lru:
                    self._lru.move_to_end(i)
            while len(self._lru) > LRU_MAX:
                self._lru.popitem(last=False)
            return out

    def _as_id(self, value) -> int:
        try:
            tid = operator.index(value)
        except TypeError as exc:
            raise TypeError(f"token id 必须是整数，收到 {value!r}") from exc
        if not 0 <= tid < self.n_vocab:
            raise IndexError(f"token id {tid} 越界（合法范围 0..{self.n_vocab - 1}）")
        return tid

    def _dequantize(self, ids: Sequence[int]) -> np.ndarray:
        """只对这几行做反量化 -> [len(ids), n_embd] float32"""
        raw = np.ascontiguousarray(self._data[list(ids)])
        vecs = dequantize(raw, self._tensor.tensor_type)
        vecs = np.asarray(vecs, dtype=np.float32)
        if vecs.shape != (len(ids), self.n_embd):
            raise ValueError(
                f"反量化结果形状 {vecs.shape} 不等于 {(len(ids), self.n_embd)}"
                f"（tensor_type={self._tensor.tensor_type}, raw={raw.shape}）"
            )
        return vecs

    # -- 整表缓存 ---------------------------------------------------------

    def _open_cache(self) -> np.ndarray | None:
        """形状/dtype 匹配则返回 mmap，否则返回 None（旧缓存一律忽略）"""
        if not self.cache_path.is_file():
            return None
        try:
            arr = np.load(self.cache_path, mmap_mode="r")
        except Exception as exc:  # 截断/半截文件都不要紧，按行反量化兜底
            logger.warning("忽略无法读取的 embedding 缓存 %s: %s", self.cache_path, exc)
            return None
        if arr.dtype != np.float32 or arr.shape != (self.n_vocab, self.n_embd):
            logger.warning(
                "忽略不匹配的 embedding 缓存 %s: dtype=%s shape=%s，期望 float32 %s",
                self.cache_path,
                arr.dtype,
                arr.shape,
                (self.n_vocab, self.n_embd),
            )
            return None
        logger.debug("复用 embedding 缓存 %s", self.cache_path)
        return arr

    def write_cache(self, path: str | Path | None = None) -> Path:
        """
        把整表反量化成 float32 落盘（流式写，峰值内存只有一块）

        1.7B 解码器的产物约 1.24 GB。写完会自动切到 mmap 读路径。

        Args:
            path: 覆盖默认缓存路径 ``<gguf>.embd.npy``

        Returns:
            实际写出的路径

        Raises:
            RuntimeError: 已 ``close()``
        """
        if self._closed:
            raise RuntimeError("TokenEmbedding 已关闭，不能再写缓存")

        target = Path(path) if path is not None else self.cache_path
        if target.is_file() and self._mmap is not None and target == self.cache_path:
            return target  # 已经在用这份缓存

        target.parent.mkdir(parents=True, exist_ok=True)
        # 先写临时文件再原子替换：中途失败不会留下半截的 .npy
        tmp = target.with_name(target.name + ".tmp")
        table = np.lib.format.open_memmap(
            tmp, mode="w+", dtype=np.float32, shape=(self.n_vocab, self.n_embd)
        )
        try:
            for start in range(0, self.n_vocab, _WRITE_CHUNK_ROWS):
                stop = min(start + _WRITE_CHUNK_ROWS, self.n_vocab)
                table[start:stop] = self._dequantize(range(start, stop))
            table.flush()
        except BaseException:
            del table
            try:
                tmp.unlink()
            except OSError:
                pass
            raise
        del table
        os.replace(tmp, target)

        with self._lock:
            self._mmap = self._open_cache()
        return target

    # -- 生命周期 ---------------------------------------------------------

    def close(self) -> None:
        """释放 mmap 与缓存（幂等；重复调用安全）"""
        if getattr(self, "_closed", True):
            return
        self._closed = True
        npy_mmap = None
        lock = getattr(self, "_lock", None)
        if lock is not None:
            with lock:
                self._lru.clear()
                npy_mmap, self._mmap = self._mmap, None
        # gguf-py 没有 close()，但 GGUF 与 .npy 都是 np.memmap 打开的；
        # Windows 上不显式关会一直占着文件锁（连删临时目录都会 WinError 32）。
        # 注意 __init__ 的失败路径里 _data 可能还不存在，必须 getattr 取。
        reader = getattr(self, "_reader", None)
        for obj in (npy_mmap, getattr(self, "_data", None), getattr(reader, "data", None)):
            mm = getattr(obj, "_mmap", None)
            if mm is not None:
                try:
                    mm.close()
                except (BufferError, OSError):
                    # 还有视图引用着（例如调用方留着 rows() 的返回值）就交给 GC
                    pass
        self._data = None
        self._tensor = None
        self._reader = None

    def __enter__(self) -> "TokenEmbedding":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        state = "closed" if getattr(self, "_closed", True) else "open"
        return (
            f"TokenEmbedding({getattr(self, 'path', '?')!r}, n_embd={getattr(self, 'n_embd', '?')}, "
            f"n_vocab={getattr(self, 'n_vocab', '?')}, {state})"
        )
