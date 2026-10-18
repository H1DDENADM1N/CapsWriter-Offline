import type { FieldMeta, PageMeta } from './types.ts';

/**
 * AI 语言表达优化用的两个服务商。
 *
 * 三处刻意的设计决定：
 * 1. `api_key` 用 `secret` 控件（掩码显示 + 一键显示），且**搜索不索引它的值**
 *    （`search.ts` 只对 `widget !== 'secret'` 的字段建值索引），否则命令面板会把
 *    sk-xxx 打到屏幕上。
 * 2. `model` 做成自由文本而不是枚举：这两家的模型名几个月就换一批，写死枚举会
 *    导致「用户从官网抄来的新模型名存不进去」。
 * 3. `base_url` 允许留空（走官方默认），但填了就必须是 http(s):// 开头。
 */

const openaiFields: FieldMeta[] = [
  {
    path: 'client.openai.api_key',
    segments: ['client', 'openai', 'api_key'],
    title: 'OpenAI API Key',
    note: '请填写您自己的 API Key\n不要泄露给任何人',
    type: 'string',
    widget: 'secret',
    default: '',
    allowEmpty: true,
    aliases: ['密钥', 'key', 'api', 'sk'],
  },
  {
    path: 'client.openai.base_url',
    segments: ['client', 'openai', 'base_url'],
    title: 'OpenAI 接口地址',
    note: '兼容 OpenAI API 的服务商填自己的 base_url，例如 https://api.siliconflow.cn/v1\n留空则使用官方 https://api.openai.com/v1',
    type: 'string',
    widget: 'text',
    default: 'https://api.siliconflow.cn/v1',
    allowEmpty: true,
    validators: ['url'],
    aliases: ['接口', '地址', 'base'],
  },
  {
    path: 'client.openai.model',
    segments: ['client', 'openai', 'model'],
    title: 'OpenAI 模型名称',
    note: [
      '硅基流动 注册邀请码：WDsBZwpv',
      'https://cloud.siliconflow.cn/i/WDsBZwpv',
      '模型名由服务商决定，这里不枚举（改名频繁）',
    ].join('\n'),
    type: 'string',
    widget: 'text',
    default: 'tencent/Hunyuan-MT-7B',
    aliases: ['模型'],
  },
];

const zhipuaiFields: FieldMeta[] = [
  {
    path: 'client.zhipuai.api_key',
    segments: ['client', 'zhipuai', 'api_key'],
    title: '智谱 API Key',
    note: '请填写您自己的 API Key\n不要泄露给任何人\n获取 API Key https://open.bigmodel.cn/usercenter/proj-mgmt/apikeys',
    type: 'string',
    widget: 'secret',
    default: '',
    allowEmpty: true,
    aliases: ['密钥', 'key', '智谱'],
  },
  {
    path: 'client.zhipuai.model',
    segments: ['client', 'zhipuai', 'model'],
    title: '智谱模型名称',
    note: '模型名称 默认免费模型 glm-4-flash-250414\n了解更多 https://open.bigmodel.cn/',
    type: 'string',
    widget: 'text',
    default: 'glm-4-flash-250414',
    aliases: ['模型', '智谱'],
  },
];

export const aiProvidersPage: PageMeta = {
  id: 'aiProviders',
  title: 'AI 服务商',
  icon: 'ai',
  sections: [
    { id: 'openai', title: 'OpenAI / 兼容 API', fields: openaiFields },
    { id: 'zhipuai', title: '智谱', fields: zhipuaiFields },
  ],
};
