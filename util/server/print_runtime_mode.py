# coding: utf-8
"""服务端启动时打印易读的「运行模式」信息。

启动日志原本只说「语音模型载入完成」，用户看不出 QwenCTC 当前跑的是纯 CTC、
两遍还是纯 LLM，也看不出编码器形态（融合 1.7B / 拆分 0.6B）、CTC 首遍是否
真的生效、有没有字级时间戳、标点由谁产出。本模块把这些收成一张表。

三个函数按职责拆分，方便分别测试：

- `build_runtime_mode_rows()` 纯函数，只算「项目 → 值」两列，不碰 stdout
- `summarize_runtime_mode()` 压成一行纯文本，写进日志文件（框线不该进 log）
- `print_runtime_mode()` 用 rich 渲染成表，打到终端

取值的字段全部来自真实对象（引擎的 ``mode`` / ``has_timestamps`` /
``_is_split`` / ``_enc.output_dim`` / ``_llm`` / ``config``，FunASR 引擎的
``config``），**一律 getattr 兜底**：展示逻辑取不到值就显示「未知」，
绝不允许因为打印启动信息把服务端起不来。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Tuple

from rich.panel import Panel
from rich.table import Table

from util.config import ParaformerArgs, SenseVoiceArgs
from util.config import ServerConfig as Config
from util.server.cosmic import console

UNKNOWN = "未知"

# 这三个字面量必须与 util/qwen_ctc/engine.py 的同名常量一致。
# 此处刻意不 import engine：那会把 onnxruntime / llama.cpp 的 ctypes 定义
# 一起拉进进程，而打印启动信息不该付这个代价。
# tests/print_runtime_mode_test.py 会断言两边一致。
MODE_CTC = "ctc"
MODE_TWO_PASS = "two_pass"
MODE_LLM = "llm"

_MODE_LABELS = {
    MODE_CTC: "纯 CTC",
    MODE_TWO_PASS: "两遍（CTC 首遍 + LLM 二遍）",
    MODE_LLM: "纯 LLM",
}


def _attr(obj: Any, name: str, default: Any = None) -> Any:
    """安全取属性：对象为 None 或缺字段时返回默认值，绝不抛异常。"""
    if obj is None:
        return default
    return getattr(obj, name, default)


def _fmt(value: Any, default: str = UNKNOWN) -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _on_off(flag: Optional[bool]) -> str:
    if flag is None:
        return UNKNOWN
    return "开" if flag else "关"


def _basename(value: Any) -> str:
    """取文件名（目录则取末级目录名），空值给「未知」。"""
    if not value:
        return UNKNOWN
    try:
        return Path(str(value)).name or UNKNOWN
    except (TypeError, ValueError):
        return UNKNOWN


def _format_text_row() -> Tuple[str, str]:
    return (
        "文本格式化",
        f"数字转换 {_on_off(Config.format_num)} · "
        f"空格整理 {_on_off(Config.format_spell)} · "
        f"标点 {_on_off(Config.format_punc)}",
    )


def _punctuation_row(punc_model: Any, fallback: str) -> Tuple[str, str]:
    """标点来源：优先如实说「标点模型已加载」，否则按开关与 fallback 说明。"""
    if punc_model is not None:
        return ("标点", "sherpa 标点模型（CT-Transformer，已加载）")
    if not Config.format_punc:
        return ("标点", "未启用（format_punc = false）")
    return ("标点", fallback)


def _qwen_ctc_rows(recognizer: Any, punc_model: Any) -> List[Tuple[str, str]]:
    mode = _fmt(_attr(recognizer, "mode"), "")
    label = _MODE_LABELS.get(mode, mode or UNKNOWN)
    # 取不到模式（对象残缺 / 引擎尚未初始化）时，其余字段都不可信：
    # 宁可显示「未知」，也不能假装知道编码器形态或 CTC 是否生效
    known_mode = mode in _MODE_LABELS
    config = _attr(recognizer, "config")
    is_split = bool(_attr(recognizer, "_is_split", False))
    dim = _attr(_attr(recognizer, "_enc"), "output_dim")

    if dim is None:
        encoder_text = "未知（取不到编码器信息）"
    elif is_split:
        encoder_text = (
            f"拆分 0.6B · {_fmt(dim)} 维 · "
            f"{_basename(_attr(config, 'encoder_frontend_path'))} + "
            f"{_basename(_attr(config, 'encoder_backend_path'))}"
        )
    else:
        encoder_text = (
            f"融合 1.7B · {_fmt(dim)} 维 · "
            f"{_basename(_attr(config, 'encoder_onnx_path'))}"
        )

    enable_ctc = _attr(config, "enable_ctc")
    if not known_mode:
        ctc_text = UNKNOWN
    elif is_split:
        # 0.6B 的编码器输出 1024 维，公开的 CTC 头都是 2048 维，没有可配的头
        ctc_text = "不可用（0.6B 拆分编码器没有配套的 CTC 头）"
    elif enable_ctc is False:
        ctc_text = "未启用（enable_ctc = false）"
    elif mode == MODE_TWO_PASS:
        ctc_text = "启用（出字级时间戳，文本由 LLM 生成）"
    elif mode == MODE_CTC:
        ctc_text = "启用（直接出文本与字级时间戳）"
    elif _attr(recognizer, "_ctc") is None:
        ctc_text = "不可用（CTC 头维度不匹配，已退化为纯 LLM）"
    else:
        ctc_text = "启用"

    llm = _attr(recognizer, "_llm")
    if not known_mode:
        llm_text = UNKNOWN
    elif llm is None:
        llm_text = "未配置（走纯 CTC）"
    else:
        llm_text = (
            f"{_basename(_attr(llm, 'path'))} · "
            f"n_ctx={_fmt(_attr(config, 'llm_n_ctx'))} · "
            f"线程={_fmt(_attr(config, 'llm_n_threads'))} · "
            f"单段最多 {_fmt(_attr(config, 'llm_n_predict'))} token · 已预热"
        )

    has_timestamps = _attr(recognizer, "has_timestamps")
    if not known_mode:
        timestamps_text = UNKNOWN
    elif has_timestamps is False:
        timestamps_text = "无（纯 LLM 不产出，客户端不生成 SRT）"
    elif mode == MODE_TWO_PASS:
        timestamps_text = "有（CTC 时间戳经 NW 对齐到 LLM 文本）"
    elif mode == MODE_CTC:
        timestamps_text = "有（CTC 原生字级）"
    else:
        timestamps_text = _fmt(has_timestamps)

    # 纯 CTC 的文本没有断句，才需要标点模型；两遍 / 纯 LLM 的标点由 LLM 产出
    if known_mode and mode == MODE_CTC:
        punc_fallback = "未加载标点模型（CTC 输出无断句）"
    else:
        punc_fallback = "由 LLM 自带（未加载标点模型）"

    rows: List[Tuple[str, str]] = [
        ("运行模式", label),
        ("编码器", encoder_text),
        ("CTC 首遍", ctc_text),
        ("LLM 解码器", llm_text),
        ("字级时间戳", timestamps_text),
        _punctuation_row(punc_model, punc_fallback),
    ]
    return rows


def _funasr_rows(recognizer: Any, punc_model: Any) -> List[Tuple[str, str]]:
    config = _attr(recognizer, "config")
    enable_ctc = _attr(config, "enable_ctc")
    return [
        (
            "解码器 GGUF",
            f"{_basename(_attr(config, 'decoder_gguf_path'))} · "
            f"n_ctx={_fmt(_attr(config, 'n_ctx'))} · "
            f"线程={_fmt(_attr(config, 'n_threads'))} · "
            f"单段最多 {_fmt(_attr(config, 'n_predict'))} token",
        ),
        (
            "CTC 首遍",
            "启用（出字级时间戳）" if enable_ctc else "未启用（无字级时间戳）",
        ),
        ("热词表", _basename(_attr(config, "hotwords_path"))),
        (
            "字级时间戳",
            "有（CTC 时间戳经 NW 对齐到 LLM 文本）"
            if enable_ctc
            else "无（LLM 只有文本）",
        ),
        _punctuation_row(punc_model, "由 LLM 自带"),
    ]


def _paraformer_rows(punc_model: Any) -> List[Tuple[str, str]]:
    return [
        ("模型目录", _basename(ParaformerArgs.paraformer)),
        ("线程数", _fmt(ParaformerArgs.num_threads)),
        ("字级时间戳", "有（模型原生）"),
        _punctuation_row(punc_model, "未加载标点模型（输出无断句）"),
    ]


def _sensevoice_rows() -> List[Tuple[str, str]]:
    return [
        ("模型文件", _basename(SenseVoiceArgs.model)),
        ("线程数", _fmt(SenseVoiceArgs.num_threads)),
        ("Provider", _fmt(SenseVoiceArgs.provider)),
        ("识别语言", _fmt(SenseVoiceArgs.language)),
        ("字级时间戳", "有（模型原生）"),
        ("标点", "由模型自带（SenseVoice 富文本输出）"),
    ]


def build_runtime_mode_rows(
    recognizer: Any = None, punc_model: Any = None
) -> List[Tuple[str, str]]:
    """算出「项目 → 值」两列，纯函数，不碰 stdout。"""
    model = _fmt(Config.model)
    rows: List[Tuple[str, str]] = [("识别模型", model)]

    if model == "QwenCTC":
        rows.extend(_qwen_ctc_rows(recognizer, punc_model))
    elif model == "FunASR":
        rows.extend(_funasr_rows(recognizer, punc_model))
    elif model == "Paraformer":
        rows.extend(_paraformer_rows(punc_model))
    elif model == "Sensevoice":
        rows.extend(_sensevoice_rows())
    else:
        rows.append(("运行模式", "未识别的模型名，无可报告的模式信息"))

    rows.append(_format_text_row())
    return rows


def summarize_runtime_mode(recognizer: Any = None, punc_model: Any = None) -> str:
    """压成一行纯文本，用于写日志文件（不带 rich 的框线）。"""
    rows = build_runtime_mode_rows(recognizer, punc_model)
    return "运行模式：" + " | ".join(f"{key}={value}" for key, value in rows)


def print_runtime_mode(
    recognizer: Any = None, punc_model: Any = None, logger: Any = None
) -> None:
    """在终端渲染「运行模式」表，并把单行摘要写进日志。"""
    rows = build_runtime_mode_rows(recognizer, punc_model)

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("项目", style="cyan", no_wrap=True)
    table.add_column("值", style="green")
    for key, value in rows:
        table.add_row(key, value)

    console.print(
        Panel(table, title="运行模式", title_align="left", border_style="green3")
    )

    if logger is not None:
        logger.info(summarize_runtime_mode(recognizer, punc_model))
