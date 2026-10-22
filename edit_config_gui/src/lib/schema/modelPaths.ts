import type { FieldMeta, PageMeta, SectionMeta } from './types.ts';

/**
 * 模型路径：5 个目录 + 15 个文件（共 20 个键）。
 *
 * 全部 `warnOnly: true` —— 校验只产出警告、绝不阻断保存。理由：模型文件动辄
 * 几个 GB，用户经常是「先改好配置，回头再下载模型」。旧 GUI 的
 * `ValueCheck.is_file_exist` 失败时也只是弹右侧提示、值照样留着，新版把这个
 * 行为明确成 `warnOnly`，语义一致但不再让人误以为保存失败。
 *
 * 15 个文件都带 `fileSuffix`。旧 GUI 调 `is_file_exist` 时**从不传后缀**
 * （`model_paths_config_page.py:287,333,377,…`），所以填个 `foo.txt` 也能过；
 * 新版补上后缀检查，但因为 warnOnly，最坏只多一条黄色提示。
 */

function dirField(
  key: string,
  title: string,
  def: string,
  alias: string,
): FieldMeta {
  return {
    path: `model_paths.${key}`,
    segments: ['model_paths', key],
    title,
    note: title,
    type: 'string',
    widget: 'path',
    pathMode: 'directory',
    default: def,
    validators: ['dirExist'],
    warnOnly: true,
    aliases: [alias, '目录', '路径'],
  };
}

function fileField(
  key: string,
  title: string,
  note: string,
  suffix: string,
  def: string,
  alias: string,
  allowEmpty?: boolean,
): FieldMeta {
  return {
    path: `model_paths.${key}`,
    segments: ['model_paths', key],
    title,
    note,
    type: 'string',
    widget: 'path',
    pathMode: 'file',
    fileSuffix: suffix,
    default: def,
    allowEmpty,
    validators: ['fileExist'],
    warnOnly: true,
    aliases: [alias, suffix.replace('.', ''), '路径'],
  };
}

const generalFields: FieldMeta[] = [
  dirField('model_dir', '模型文件目录', 'models', '模型'),
  dirField(
    'punc_model_dir',
    '标点模型目录',
    'models/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12',
    '标点',
  ),
];

const funasrFields: FieldMeta[] = [
  dirField(
    'funasr_dir',
    'FunASR 路径',
    'models/Fun-ASR-Nano-GGUF-2026-02-09',
    'FunASR',
  ),
  fileField(
    'funasr_encoder_adaptor_path',
    'FunASR encoder_adaptor 模型路径',
    'FunASR encoder_adaptor 模型路径',
    '.onnx',
    'models/Fun-ASR-Nano-GGUF-2026-02-09/model/Fun-ASR-Nano-Encoder-Adaptor.int8.onnx',
    'encoder',
  ),
  fileField(
    'funasr_ctc_path',
    'CTC 快速预识别模型路径',
    'CTC 快速预识别',
    '.onnx',
    'models/Fun-ASR-Nano-GGUF-2026-02-09/model/Fun-ASR-Nano-CTC.int8.onnx',
    'CTC',
  ),
  fileField(
    'funasr_llm_path',
    'FunASR llm 模型路径',
    'FunASR llm 模型路径',
    '.gguf',
    'models/Fun-ASR-Nano-GGUF-2026-02-09/model/Fun-ASR-Nano-Decoder.q8_0.gguf',
    'llm',
  ),
  fileField(
    'funasr_tokens_path',
    'FunASR tokens 路径',
    'FunASR tokens 路径',
    '.txt',
    'models/Fun-ASR-Nano-GGUF-2026-02-09/model/tokens.txt',
    'tokens',
  ),
  fileField(
    'funasr_hotwords_path',
    'FunASR 热词文件路径',
    'FunASR 热词文件路径',
    '.txt',
    'models/Fun-ASR-Nano-GGUF-2026-02-09/hot.txt',
    '热词',
  ),
];

const sensevoiceFields: FieldMeta[] = [
  fileField(
    'sensevoice_path',
    'SenseVoice 模型路径',
    'SenseVoice 模型路径',
    '.onnx',
    'models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/model.int8.onnx',
    'SenseVoice',
  ),
  fileField(
    'sensevoice_tokens_path',
    'SenseVoice tokens 路径',
    'SenseVoice tokens 路径',
    '.txt',
    'models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt',
    'tokens',
  ),
];

const paraformerFields: FieldMeta[] = [
  fileField(
    'paraformer_path',
    'Paraformer 模型路径',
    'Paraformer 模型路径',
    '.onnx',
    'models/paraformer-offline-zh/model.int8.onnx',
    'Paraformer',
  ),
  fileField(
    'paraformer_tokens_path',
    'Paraformer tokens 路径',
    'Paraformer tokens 路径',
    '.txt',
    'models/paraformer-offline-zh/tokens.txt',
    'tokens',
  ),
];

const qwenCtcFields: FieldMeta[] = [
  fileField(
    'qwen_ctc_encoder_path',
    'Qwen3-ASR 编码器模型路径',
    'Qwen3-ASR 编码器模型路径',
    '.onnx',
    'models/qwen-ctc-aiinfra4/Qwen3-ASR-Encoder.q4.onnx',
    'encoder',
  ),
  fileField(
    'qwen_ctc_ctc_path',
    'Qwen3-ASR CTC 头模型路径',
    'Qwen3-ASR CTC 头模型路径',
    '.onnx',
    'models/qwen-ctc-aiinfra4/Qwen3-ASR-CTC.v1.fp16.onnx',
    'CTC',
  ),
  fileField(
    'qwen_ctc_tokens_path',
    'Qwen3-ASR CTC 紧凑词表路径',
    'Qwen3-ASR CTC 紧凑词表路径（base64 原始字节）',
    '.txt',
    'models/qwen-ctc-aiinfra4/tokens.txt',
    'tokens',
  ),
  dirField(
    'qwen_ctc_preprocessor_path',
    'Qwen3-ASR 特征提取器配置目录',
    'models/qwen-ctc-aiinfra4',
    'preprocessor',
  ),
  fileField(
    'qwen_llm_path',
    'Qwen3-ASR LLM 解码器（GGUF）路径',
    'Qwen3-ASR LLM 解码器（GGUF）路径，留空则退回纯 CTC 模式',
    '.gguf',
    'models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf',
    'llm',
    true,
  ),
  fileField(
    'qwen_ctc_encoder_frontend_path',
    '0.6B 编码器前端（ONNX）路径',
    '0.6B 编码器前端（ONNX）路径，留空则用上面的融合编码器（1.7B）',
    '.onnx',
    '',
    'frontend',
    true,
  ),
  fileField(
    'qwen_ctc_encoder_backend_path',
    '0.6B 编码器后端（ONNX）路径',
    '0.6B 编码器后端（ONNX）路径，留空则用上面的融合编码器（1.7B）',
    '.onnx',
    '',
    'backend',
    true,
  ),
];

const opusMtFields: FieldMeta[] = [
  dirField(
    'opus_mt_dir',
    '离线翻译模型目录',
    'models/Helsinki-NLP--opus-mt-zh-en',
    'opus',
  ),
];

const sections: SectionMeta[] = [
  {
    id: 'general',
    title: '通用',
    note: '路径可以是相对仓库根的相对路径（默认），也可以是绝对路径。文件缺失只提示、不阻止保存。',
    fields: generalFields,
  },
  { id: 'funasr', title: 'FunASR 语音模型', fields: funasrFields },
  { id: 'sensevoice', title: 'SenseVoice 语音模型', fields: sensevoiceFields },
  { id: 'paraformer', title: 'Paraformer 语音模型', fields: paraformerFields },
  { id: 'qwenCtc', title: 'Qwen3-ASR + CTC 头 语音模型', fields: qwenCtcFields },
  {
    id: 'opusMt',
    title: 'Helsinki NLP--opus-mt-zh-en 离线翻译模型',
    fields: opusMtFields,
  },
];

export const modelPathsPage: PageMeta = {
  id: 'modelPaths',
  title: '模型路径',
  icon: 'folder',
  sections,
};
