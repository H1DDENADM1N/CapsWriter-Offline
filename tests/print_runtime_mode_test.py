# coding: utf-8
"""tests/print_runtime_mode_test.py

覆盖 `util/server/print_runtime_mode.py`：

1. 模式字面量与 `util/qwen_ctc/engine.py` 的常量一致（两者不能漂移）
2. QwenCTC 三种模式 + 0.6B 拆分 + CTC 头维度不匹配降级，行内容正确
3. FunASR / Paraformer / Sensevoice 的行内容正确
4. 取不到字段（recognizer=None 或残缺对象）时不抛异常，显示「未知」
5. 单行摘要不含换行

跑法：`python tests/print_runtime_mode_test.py`（或用仓库内置的 python，
如 `./.venv/Scripts/python.exe tests/print_runtime_mode_test.py`）
"""

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from util.config import ServerConfig as Config
from util.server.print_runtime_mode import (
    MODE_CTC,
    MODE_LLM,
    MODE_TWO_PASS,
    build_runtime_mode_rows,
    print_runtime_mode,
    summarize_runtime_mode,
)


# ---------------------------------------------------------------- 工具函数


def _as_dict(rows):
    """行列表 → 字典，重复键取最后一个（本表没有重复键）。"""
    return dict(rows)


class _ModelSwitch:
    """临时切换 Config.model / 三个格式化开关，退出时还原。"""

    def __init__(self, model, *, format_num=True, format_punc=True, format_spell=True):
        self.model = model
        self.flags = (format_num, format_punc, format_spell)

    def __enter__(self):
        self._saved = (Config.model, Config.format_num, Config.format_punc, Config.format_spell)
        Config.model = self.model
        Config.format_num, Config.format_punc, Config.format_spell = self.flags
        return self

    def __exit__(self, *exc_info):
        (
            Config.model,
            Config.format_num,
            Config.format_punc,
            Config.format_spell,
        ) = self._saved
        return False


def _qwen_recognizer(
    mode,
    *,
    is_split=False,
    enable_ctc=True,
    has_ctc_head=True,
    has_llm=True,
    dim=2048,
):
    """造一个形状与 QwenCTCEngine 一致的假对象。"""
    config = SimpleNamespace(
        encoder_onnx_path="models/qwen-ctc-aiinfra4/Qwen3-ASR-Encoder.q4.onnx",
        encoder_frontend_path=(
            "models/qwen-ctc-aiinfra4-06b/qwen3_asr_encoder_frontend.int4.onnx"
        ),
        encoder_backend_path=(
            "models/qwen-ctc-aiinfra4-06b/qwen3_asr_encoder_backend.int4.onnx"
        ),
        enable_ctc=enable_ctc,
        llm_n_ctx=4096,
        llm_n_threads=6,
        llm_n_predict=256,
    )
    return SimpleNamespace(
        mode=mode,
        has_timestamps=mode in (MODE_CTC, MODE_TWO_PASS),
        config=config,
        _is_split=is_split,
        _enc=SimpleNamespace(output_dim=dim),
        _ctc=object() if has_ctc_head else None,
        _llm=(
            SimpleNamespace(
                path=Path("models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf")
            )
            if has_llm
            else None
        ),
    )


def _funasr_recognizer(*, enable_ctc=True):
    config = SimpleNamespace(
        decoder_gguf_path="models/Fun-ASR-Nano-GGUF-2026-02-09/model/Fun-ASR-Nano-Decoder.q8_0.gguf",
        n_ctx=2048,
        n_threads=6,
        n_predict=512,
        enable_ctc=enable_ctc,
        hotwords_path="models/Fun-ASR-Nano-GGUF-2026-02-09/model/hot.txt",
    )
    return SimpleNamespace(config=config)


# ---------------------------------------------------------------- 用例


def test_mode_literals_match_engine_constants():
    """两个模块的模式字面量必须一致，否则本模块会把模式名认错。"""
    from util.qwen_ctc import engine as qwen_engine

    assert MODE_CTC == qwen_engine.MODE_CTC
    assert MODE_TWO_PASS == qwen_engine.MODE_TWO_PASS
    assert MODE_LLM == qwen_engine.MODE_LLM
    print("[OK] 模式字面量与 util/qwen_ctc/engine.py 一致")


def test_qwen_ctc_two_pass_rows():
    recognizer = _qwen_recognizer(MODE_TWO_PASS)
    with _ModelSwitch("QwenCTC"):
        rows = _as_dict(build_runtime_mode_rows(recognizer, SimpleNamespace()))

    assert rows["识别模型"] == "QwenCTC"
    assert rows["运行模式"] == "两遍（CTC 首遍 + LLM 二遍）"
    assert rows["编码器"] == "融合 1.7B · 2048 维 · Qwen3-ASR-Encoder.q4.onnx"
    assert rows["CTC 首遍"] == "启用（出字级时间戳，文本由 LLM 生成）"
    assert "qwen3_asr_llm.q4_k.gguf" in rows["LLM 解码器"]
    assert "n_ctx=4096" in rows["LLM 解码器"]
    assert "线程=6" in rows["LLM 解码器"]
    assert "单段最多 256 token" in rows["LLM 解码器"]
    assert rows["字级时间戳"] == "有（CTC 时间戳经 NW 对齐到 LLM 文本）"
    assert rows["标点"] == "sherpa 标点模型（CT-Transformer，已加载）"
    assert rows["文本格式化"] == "数字转换 开 · 空格整理 开 · 标点 开"
    print("[OK] 两遍模式行内容正确")


def test_qwen_ctc_pure_ctc_rows():
    recognizer = _qwen_recognizer(MODE_CTC, has_llm=False)
    with _ModelSwitch("QwenCTC"):
        rows = _as_dict(build_runtime_mode_rows(recognizer, None))

    assert rows["运行模式"] == "纯 CTC"
    assert rows["CTC 首遍"] == "启用（直接出文本与字级时间戳）"
    assert rows["LLM 解码器"] == "未配置（走纯 CTC）"
    assert rows["字级时间戳"] == "有（CTC 原生字级）"
    # 没传标点模型、format_punc 为真 → 如实说「未加载」
    assert rows["标点"] == "未加载标点模型（CTC 输出无断句）"
    print("[OK] 纯 CTC 模式行内容正确")


def test_qwen_ctc_pure_llm_rows_warns_no_timestamps():
    recognizer = _qwen_recognizer(MODE_LLM, enable_ctc=False, has_ctc_head=False)
    with _ModelSwitch("QwenCTC"):
        rows = _as_dict(build_runtime_mode_rows(recognizer, None))

    assert rows["运行模式"] == "纯 LLM"
    assert rows["CTC 首遍"] == "未启用（enable_ctc = false）"
    assert rows["字级时间戳"] == "无（纯 LLM 不产出，客户端不生成 SRT）"
    print("[OK] 纯 LLM 模式行内容正确")


def test_qwen_ctc_split_encoder_reports_no_ctc_head():
    """0.6B 拆分编码器没有配套 CTC 头，必须如实说明原因。"""
    recognizer = _qwen_recognizer(MODE_LLM, is_split=True, dim=1024, has_ctc_head=False)
    with _ModelSwitch("QwenCTC"):
        rows = _as_dict(build_runtime_mode_rows(recognizer, None))

    assert rows["编码器"].startswith("拆分 0.6B · 1024 维 · ")
    assert "qwen3_asr_encoder_frontend.int4.onnx" in rows["编码器"]
    assert "qwen3_asr_encoder_backend.int4.onnx" in rows["编码器"]
    assert rows["CTC 首遍"] == "不可用（0.6B 拆分编码器没有配套的 CTC 头）"
    assert rows["字级时间戳"] == "无（纯 LLM 不产出，客户端不生成 SRT）"
    print("[OK] 0.6B 拆分编码器行内容正确")


def test_qwen_ctc_head_dim_mismatch_reports_degradation():
    """请求了两遍但 CTC 头维度不匹配 → 引擎降级为纯 LLM，展示也要说清。"""
    recognizer = _qwen_recognizer(MODE_LLM, enable_ctc=True, has_ctc_head=False)
    with _ModelSwitch("QwenCTC"):
        rows = _as_dict(build_runtime_mode_rows(recognizer, None))

    assert rows["运行模式"] == "纯 LLM"
    assert rows["CTC 首遍"] == "不可用（CTC 头维度不匹配，已退化为纯 LLM）"
    print("[OK] CTC 头维度不匹配的降级说明正确")


def test_qwen_ctc_two_pass_without_punc_model_says_llm_carries_punc():
    """两遍模式不加载标点模型，标点由 LLM 产出 —— 不能写成「CTC 输出无断句」。"""
    recognizer = _qwen_recognizer(MODE_TWO_PASS)
    with _ModelSwitch("QwenCTC"):
        rows = _as_dict(build_runtime_mode_rows(recognizer, None))

    assert rows["标点"] == "由 LLM 自带（未加载标点模型）"
    print("[OK] 两遍模式无标点模型时的说明正确")


def test_funasr_rows():
    with _ModelSwitch("FunASR"):
        rows = _as_dict(build_runtime_mode_rows(_funasr_recognizer(), None))

    assert rows["识别模型"] == "FunASR"
    assert "Fun-ASR-Nano-Decoder.q8_0.gguf" in rows["解码器 GGUF"]
    assert "n_ctx=2048" in rows["解码器 GGUF"]
    assert "单段最多 512 token" in rows["解码器 GGUF"]
    assert rows["CTC 首遍"] == "启用（出字级时间戳）"
    assert rows["热词表"] == "hot.txt"
    assert rows["字级时间戳"] == "有（CTC 时间戳经 NW 对齐到 LLM 文本）"
    assert rows["标点"] == "由 LLM 自带"
    print("[OK] FunASR 行内容正确")


def test_funasr_rows_without_ctc():
    with _ModelSwitch("FunASR"):
        rows = _as_dict(
            build_runtime_mode_rows(_funasr_recognizer(enable_ctc=False), None)
        )

    assert rows["CTC 首遍"] == "未启用（无字级时间戳）"
    assert rows["字级时间戳"] == "无（LLM 只有文本）"
    print("[OK] FunASR 关闭 CTC 时行内容正确")


def test_paraformer_rows():
    with _ModelSwitch("Paraformer"):
        rows = _as_dict(build_runtime_mode_rows(None, None))

    assert rows["识别模型"] == "Paraformer"
    assert rows["字级时间戳"] == "有（模型原生）"
    assert rows["标点"] == "未加载标点模型（输出无断句）"
    print("[OK] Paraformer 行内容正确")


def test_paraformer_rows_reports_punc_switch_off():
    with _ModelSwitch("Paraformer", format_punc=False):
        rows = _as_dict(build_runtime_mode_rows(None, None))

    assert rows["标点"] == "未启用（format_punc = false）"
    assert rows["文本格式化"] == "数字转换 开 · 空格整理 开 · 标点 关"
    print("[OK] 关闭标点开关时行内容正确")


def test_sensevoice_rows():
    with _ModelSwitch("Sensevoice"):
        rows = _as_dict(build_runtime_mode_rows(None, None))

    assert rows["识别模型"] == "Sensevoice"
    assert rows["字级时间戳"] == "有（模型原生）"
    assert rows["标点"] == "由模型自带（SenseVoice 富文本输出）"
    print("[OK] Sensevoice 行内容正确")


def test_unknown_model_row():
    with _ModelSwitch("NotAModel"):
        rows = _as_dict(build_runtime_mode_rows(None, None))

    assert rows["识别模型"] == "NotAModel"
    assert rows["运行模式"] == "未识别的模型名，无可报告的模式信息"
    print("[OK] 未知模型名不崩、有说明")


def test_broken_recognizer_does_not_raise():
    """展示逻辑取不到字段时必须显示「未知」，绝不能把服务端启动搞挂。"""
    with _ModelSwitch("QwenCTC"):
        rows = _as_dict(build_runtime_mode_rows(object(), None))

    assert rows["运行模式"] == "未知"
    assert rows["编码器"] == "未知（取不到编码器信息）"
    # 模式不可信时，CTC / LLM / 时间戳一律不许瞎猜
    assert rows["CTC 首遍"] == "未知"
    assert rows["LLM 解码器"] == "未知"
    assert rows["字级时间戳"] == "未知"
    print("[OK] 残缺对象取不到字段时不抛异常且不瞎猜")


def test_summary_is_single_line():
    recognizer = _qwen_recognizer(MODE_TWO_PASS)
    with _ModelSwitch("QwenCTC"):
        summary = summarize_runtime_mode(recognizer, SimpleNamespace())

    assert "\n" not in summary
    assert summary.startswith("运行模式：")
    assert "识别模型=QwenCTC" in summary
    assert "字级时间戳=" in summary
    print("[OK] 单行摘要不含换行")


def test_print_runtime_mode_smoke():
    """真正渲染一次（rich 表格 + 日志行），确保不抛异常。"""
    logged = []

    class _Logger:
        def info(self, message):
            logged.append(message)

    recognizer = _qwen_recognizer(MODE_TWO_PASS)
    with _ModelSwitch("QwenCTC"):
        print_runtime_mode(recognizer, SimpleNamespace(), _Logger())

    assert len(logged) == 1
    assert logged[0].startswith("运行模式：")
    print("[OK] 渲染与日志写入正常")


if __name__ == "__main__":
    tests = [
        test_mode_literals_match_engine_constants,
        test_qwen_ctc_two_pass_rows,
        test_qwen_ctc_pure_ctc_rows,
        test_qwen_ctc_pure_llm_rows_warns_no_timestamps,
        test_qwen_ctc_split_encoder_reports_no_ctc_head,
        test_qwen_ctc_head_dim_mismatch_reports_degradation,
        test_qwen_ctc_two_pass_without_punc_model_says_llm_carries_punc,
        test_funasr_rows,
        test_funasr_rows_without_ctc,
        test_paraformer_rows,
        test_paraformer_rows_reports_punc_switch_off,
        test_sensevoice_rows,
        test_unknown_model_row,
        test_broken_recognizer_does_not_raise,
        test_summary_is_single_line,
        test_print_runtime_mode_smoke,
    ]
    for test in tests:
        test()
    print(f"\n全部通过（{len(tests)} 个用例）")
