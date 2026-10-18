import type { FieldMeta, PageMeta } from './types.ts';

/**
 * 三个本地语音识别引擎的参数页（FunASR / SenseVoice / Paraformer）。
 *
 * **9 个派生只读键**（`funasr_args.*_path`、`sensevoice_args.model/tokens`、
 * `paraformer_args.paraformer/tokens`）：
 * 它们在 config.toml 里的值是 `${model_paths.xxx}` 这样的占位符，而仓库里
 * **没有任何代码解析这种占位符**——`util/config.py:241-278` 的
 * `FunASRArgs`/`SenseVoiceArgs`/`ParaformerArgs` 直接去读 `model_paths` 段。
 * 也就是说这 9 个键改了不生效。所以它们在 UI 里是只读的，`derivedFrom` 指到真正
 * 生效的那一项；保存时既不改也不删（保留 TOML 结构）。
 */

const SAMPLE_RATE_OPTIONS = [
  { value: '16000', label: '16000（16kHz，模型默认）' },
  { value: '44100', label: '44100（44.1kHz）' },
  { value: '48000', label: '48000（48kHz）' },
];

const PROVIDER_OPTIONS = [
  { value: 'cpu', label: 'cpu' },
  { value: 'cuda', label: 'cuda' },
  { value: 'coreml', label: 'coreml' },
];

const LANGUAGE_OPTIONS = [
  { value: 'auto', label: 'auto（自动识别）' },
  { value: 'zh', label: 'zh（中文）' },
  { value: 'en', label: 'en（英文）' },
  { value: 'ja', label: 'ja（日文）' },
  { value: 'ko', label: 'ko（韩文）' },
  { value: 'yue', label: 'yue（粤语）' },
];

/** 派生只读键：只展示「实际生效值」，不写回 TOML */
function derived(
  section: string,
  key: string,
  title: string,
  sourceKey: string,
): FieldMeta {
  return {
    path: `${section}.${key}`,
    segments: [section, key],
    title,
    note: '该键是占位符（${model_paths.…}），程序不会解析它；真正生效的是「模型路径」页里的那一项。',
    type: 'string',
    widget: 'readonly',
    derivedFrom: ['model_paths', sourceKey],
  };
}

/** 三个引擎共用的 int 键 */
function intField(
  section: string,
  key: string,
  title: string,
  note: string,
  min: number,
  max: number,
): FieldMeta {
  return {
    path: `${section}.${key}`,
    segments: [section, key],
    title,
    note,
    type: 'integer',
    widget: 'int',
    min,
    max,
    aliases: [title],
  };
}

// ─────────────────────────────── FunASR ───────────────────────────────

const funasrFields: FieldMeta[] = [
  derived('funasr_args', 'encoder_onnx_path', 'encoder_adaptor 模型路径', 'funasr_encoder_adaptor_path'),
  derived('funasr_args', 'ctc_onnx_path', 'CTC 快速预识别 模型路径', 'funasr_ctc_path'),
  derived('funasr_args', 'decoder_gguf_path', 'llm 模型路径', 'funasr_llm_path'),
  derived('funasr_args', 'tokens_path', 'tokens 路径', 'funasr_tokens_path'),
  derived('funasr_args', 'hotwords_path', '热词文件路径', 'funasr_hotwords_path'),
  {
    path: 'funasr_args.enable_ctc',
    segments: ['funasr_args', 'enable_ctc'],
    title: '启用 CTC 快速预识别',
    note: '是否启用 CTC 快速预识别',
    type: 'boolean',
    widget: 'bool',
    default: true,
    aliases: ['CTC'],
  },
  intField('funasr_args', 'n_predict', 'LLM 最大生成 token 数', 'LLM 最大生成 token 数', 1, 2048),
  intField('funasr_args', 'n_threads', '线程数', '线程数，0 表示自动', 0, 32),
  {
    path: 'funasr_args.similar_threshold',
    segments: ['funasr_args', 'similar_threshold'],
    title: '热词相似度阈值',
    note: '热词相似度阈值',
    type: 'float',
    widget: 'float',
    min: 0.3,
    max: 1.0,
    step: 0.1,
    default: 0.6,
    aliases: ['热词', '阈值'],
  },
  intField('funasr_args', 'max_hotwords', '每次替换的最大热词数', '每次替换的最大热词数', 1, 100),
  {
    path: 'funasr_args.directml_enable',
    segments: ['funasr_args', 'directml_enable'],
    title: '启用 DirectML 加速 GPU 推理',
    note: '是否启用 DirectML 加速 GPU 推理\n默认禁用，兼顾 AMD 显卡 用户\n建议非 AMD 显卡 用户自行手动启用',
    type: 'boolean',
    widget: 'bool',
    default: false,
    aliases: ['DirectML', 'AMD', 'GPU'],
  },
  {
    path: 'funasr_args.vulkan_enable',
    segments: ['funasr_args', 'vulkan_enable'],
    title: '启用 Vulkan 加速 GPU 推理',
    note: '是否启用 Vulkan 加速 GPU 推理',
    type: 'boolean',
    widget: 'bool',
    default: true,
    aliases: ['Vulkan', 'GPU'],
  },
  {
    path: 'funasr_args.vulkan_force_fp32',
    segments: ['funasr_args', 'vulkan_force_fp32'],
    title: '强制 FP32 计算',
    note: '是否强制 FP32 计算（如果 GPU 是 Intel 集显且出现精度溢出，可设为 true）',
    type: 'boolean',
    widget: 'bool',
    default: false,
    aliases: ['FP32', 'Intel'],
  },
  {
    path: 'funasr_args.flash_attn',
    segments: ['funasr_args', 'flash_attn'],
    title: '启用 flash-attention',
    note: '是否启用 flash-attention（默认关闭，避免部分后端/GPU 下输出 NaN 或乱码）',
    type: 'boolean',
    widget: 'bool',
    default: false,
    aliases: ['flash', 'attention'],
  },
  {
    path: 'funasr_args.verbose',
    segments: ['funasr_args', 'verbose'],
    title: '输出详细日志',
    note: '是否输出详细日志',
    type: 'boolean',
    widget: 'bool',
    default: false,
    aliases: ['日志'],
  },
];

// ───────────────────────────── SenseVoice ─────────────────────────────

const sensevoiceFields: FieldMeta[] = [
  derived('sensevoice_args', 'model', 'SenseVoice 模型路径', 'sensevoice_path'),
  derived('sensevoice_args', 'tokens', 'SenseVoice tokens 路径', 'sensevoice_tokens_path'),
  intField('sensevoice_args', 'num_threads', '使用的线程数', '使用的线程数', 1, 32),
  {
    path: 'sensevoice_args.sample_rate',
    segments: ['sensevoice_args', 'sample_rate'],
    title: '采样率',
    note: '采样率',
    type: 'integer',
    widget: 'enum',
    options: SAMPLE_RATE_OPTIONS,
    default: 16000,
    aliases: ['采样率', 'rate'],
  },
  intField('sensevoice_args', 'feature_dim', '特征维度', '特征维度', 1, 1024),
  {
    path: 'sensevoice_args.decoding_method',
    segments: ['sensevoice_args', 'decoding_method'],
    title: '解码方法',
    note: '解码方法',
    type: 'string',
    widget: 'text',
    default: 'greedy_search',
    aliases: ['解码'],
  },
  {
    path: 'sensevoice_args.debug',
    segments: ['sensevoice_args', 'debug'],
    title: '启用调试模式',
    note: '是否启用调试模式',
    type: 'boolean',
    widget: 'bool',
    default: false,
    aliases: ['调试'],
  },
  {
    path: 'sensevoice_args.provider',
    segments: ['sensevoice_args', 'provider'],
    title: '推理设备',
    note: '推理设备（cpu, cuda, coreml）',
    type: 'string',
    widget: 'enum',
    options: PROVIDER_OPTIONS,
    default: 'cpu',
    aliases: ['设备', 'provider'],
  },
  {
    path: 'sensevoice_args.language',
    segments: ['sensevoice_args', 'language'],
    title: '识别语言',
    note: '识别语言（auto, zh, en, ja, ko, yue）',
    type: 'string',
    widget: 'enum',
    options: LANGUAGE_OPTIONS,
    default: 'auto',
    aliases: ['语言', 'language'],
  },
  {
    path: 'sensevoice_args.use_itn',
    segments: ['sensevoice_args', 'use_itn'],
    title: '使用逆文本归一化',
    note: '是否使用逆文本归一化',
    type: 'boolean',
    widget: 'bool',
    default: true,
    aliases: ['ITN', '归一化'],
  },
  {
    path: 'sensevoice_args.rule_fsts',
    segments: ['sensevoice_args', 'rule_fsts'],
    title: '自定义规则 FST 文件路径',
    note: '自定义规则 FST 文件路径\n多个文件用逗号分隔；留空表示不使用',
    type: 'string',
    widget: 'text',
    default: '',
    allowEmpty: true,
    aliases: ['规则', 'FST'],
  },
  {
    path: 'sensevoice_args.rule_fars',
    segments: ['sensevoice_args', 'rule_fars'],
    title: '自定义规则 FAR 文件路径',
    note: '自定义规则 FAR 文件路径\n多个文件用逗号分隔；留空表示不使用',
    type: 'string',
    widget: 'text',
    default: '',
    allowEmpty: true,
    aliases: ['规则', 'FAR'],
  },
];

// ───────────────────────────── Paraformer ─────────────────────────────

const paraformerFields: FieldMeta[] = [
  derived('paraformer_args', 'paraformer', 'Paraformer 模型路径', 'paraformer_path'),
  derived('paraformer_args', 'tokens', 'Paraformer tokens 路径', 'paraformer_tokens_path'),
  intField('paraformer_args', 'num_threads', '使用的线程数', '使用的线程数', 1, 32),
  {
    path: 'paraformer_args.sample_rate',
    segments: ['paraformer_args', 'sample_rate'],
    title: '采样率',
    note: '采样率',
    type: 'integer',
    widget: 'enum',
    options: SAMPLE_RATE_OPTIONS,
    default: 16000,
    aliases: ['采样率', 'rate'],
  },
  intField('paraformer_args', 'feature_dim', '特征维度', '特征维度', 1, 1024),
  {
    path: 'paraformer_args.decoding_method',
    segments: ['paraformer_args', 'decoding_method'],
    title: '解码方法',
    note: '解码方法',
    type: 'string',
    widget: 'text',
    default: 'greedy_search',
    aliases: ['解码'],
  },
  {
    path: 'paraformer_args.debug',
    segments: ['paraformer_args', 'debug'],
    title: '启用调试模式',
    note: '是否启用调试模式',
    type: 'boolean',
    widget: 'bool',
    default: false,
    aliases: ['调试'],
  },
];

export const funasrPage: PageMeta = {
  id: 'funasr',
  title: 'FunASR 参数',
  icon: 'cpu',
  sections: [
    {
      id: 'general',
      title: '通用',
      note: '前 5 项是只读派生键，真正生效的是「模型路径」页；其余是 LLM 推理参数。',
      fields: funasrFields,
    },
  ],
};

export const sensevoicePage: PageMeta = {
  id: 'sensevoice',
  title: 'SenseVoice 参数',
  icon: 'cpu',
  sections: [{ id: 'general', title: '通用', fields: sensevoiceFields }],
};

export const paraformerPage: PageMeta = {
  id: 'paraformer',
  title: 'Paraformer 参数',
  icon: 'cpu',
  sections: [{ id: 'general', title: '通用', fields: paraformerFields }],
};
