import type { FieldMeta, PageMeta, SectionMeta } from './types.ts';

/**
 * 模型路径：4 个目录 + 9 个文件。
 *
 * 全部 `warnOnly: true` —— 校验只产出警告、绝不阻断保存。理由：模型文件动辄
 * 几个 GB，用户经常是「先改好配置，回头再下载模型」。旧 GUI 的
 * `ValueCheck.is_file_exist` 失败时也只是弹右侧提示、值照样留着，新版把这个
 * 行为明确成 `warnOnly`，语义一致但不再让人误以为保存失败。
 *
 * 9 个文件都带 `fileSuffix`。旧 GUI 调 `is_file_exist` 时**从不传后缀**
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
