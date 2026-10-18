import type { FieldMeta, PageMeta } from './types.ts';

/**
 * 8 种提示风格的正文与切换快捷键（共 16 个键）。
 *
 * 正文用 `longText`：这是**唯一允许换行**的控件（规格 §8 的 `singleLine`
 * 校验器对其它所有字符串键生效）。
 *
 * 正文刻意**不给 `default`**：模板里的默认文本是 8 段 460~585 字的中文 prompt，
 * 抄进 schema 会让 bundle 白多 4KB+；更要紧的是用户改过的正文不该被「恢复默认」
 * 一键盖掉。`configStore.resetValue` 对没有 `default` 的字段回退到「本次打开时
 * 的原始值」，语义正好。
 */

interface StyleSpec {
  /** config.toml 里键名的后缀，同时是 prompt_style_selection 的取值 */
  id: string;
  /** UI 标题（取自 config.toml 注释里的风格简称） */
  title: string;
  /** 注释里的全称，用于生成副标题与快捷键说明 */
  fullName: string;
  /** 出厂快捷键 */
  hotkey: string;
}

const STYLES: StyleSpec[] = [
  {
    id: 'official',
    title: '正式公文',
    fullName: '正式公文文本校对助手',
    hotkey: 'ctrl + alt + shift + f1',
  },
  {
    id: 'sweetheart',
    title: '贴心男友',
    fullName: '贴心男友式文本润色助手',
    hotkey: 'ctrl + alt + shift + f2',
  },
  {
    id: 'social',
    title: '社交媒体',
    fullName: '社交媒体文案优化助手',
    hotkey: 'ctrl + alt + shift + f3',
  },
  {
    id: 'poetry',
    title: '仿古诗',
    fullName: '古诗创作助手',
    hotkey: 'ctrl + alt + shift + f4',
  },
  {
    id: 'english',
    title: '英文润色',
    fullName: '英文润色助手',
    hotkey: 'ctrl + alt + shift + f5',
  },
  {
    id: 'academic',
    title: '学术论文',
    fullName: '学术论文优化助手',
    hotkey: 'ctrl + alt + shift + f6',
  },
  {
    id: 'customer_service',
    title: '客户服务回复',
    fullName: '客户服务回复优化助手',
    hotkey: 'ctrl + alt + shift + f7',
  },
  {
    id: 'creative_writing',
    title: '创意写作',
    fullName: '创意写作优化助手',
    hotkey: 'ctrl + alt + shift + f8',
  },
];

function bodyField(s: StyleSpec): FieldMeta {
  return {
    path: `client.prompt_style.prompt_${s.id}`,
    segments: ['client', 'prompt_style', `prompt_${s.id}`],
    title: `${s.title} · 提示词正文`,
    note: `发送给 AI 的系统提示词（${s.fullName}）。支持多行；留空则该风格不可用。`,
    type: 'string',
    widget: 'longText',
    allowEmpty: true,
    aliases: ['提示词', 'prompt', s.title, s.id],
  };
}

function shortcutField(s: StyleSpec): FieldMeta {
  return {
    path: `client.prompt_style.prompt_${s.id}_shortcut`,
    segments: ['client', 'prompt_style', `prompt_${s.id}_shortcut`],
    title: `${s.title} · 切换快捷键`,
    note: `切换提示风格为${s.fullName}的快捷键\n注意避免快捷键冲突\n留空则 不绑定`,
    // TOML 里是字符串，且注释明确写「留空则 不绑定」
    type: 'string',
    widget: 'hotkey',
    allowEmpty: true,
    default: s.hotkey,
    validators: ['hotkey'],
    aliases: ['快捷键', s.title, s.id],
  };
}

export const promptStylesPage: PageMeta = {
  id: 'promptStyles',
  title: '提示风格',
  icon: 'palette',
  sections: [
    {
      id: 'styles',
      title: '8 种提示风格',
      note: '每种风格一张卡片：提示词正文（可多行）+ 切换快捷键（留空表示不绑定）。',
      fields: STYLES.flatMap((s) => [bodyField(s), shortcutField(s)]),
    },
  ],
};
