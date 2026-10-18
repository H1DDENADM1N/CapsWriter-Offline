import type { FieldMeta, PageMeta } from './types.ts';

const libretranslateFields: FieldMeta[] = [
  {
    path: 'libretranslate.api',
    segments: ['libretranslate', 'api'],
    title: 'LibreTranslate 离/在线翻译地址',
    note: [
      '官方 https://libretranslate.com/ 需要API Key，https://portal.libretranslate.com/',
      '建议自行部署 https://github.com/LibreTranslate/LibreTranslate',
      'Libre Translate 离/在线翻译地址',
      '如果此地址不可用（ 返回非 200 状态码），则使用 DeepLX 作为在线翻译服务',
    ].join('\n'),
    type: 'string',
    widget: 'text',
    default: 'https://libretranslate.com/',
    validators: ['url'],
    aliases: ['翻译', '地址'],
  },
];

const deeplxFields: FieldMeta[] = [
  {
    path: 'deeplx.online_translate_port',
    segments: ['deeplx', 'online_translate_port'],
    title: 'DeepLX 在线翻译服务端口',
    note: 'DeepLX 在线翻译服务端口',
    // TOML 里是字符串 "1188"
    type: 'string',
    widget: 'text',
    default: '1188',
    validators: ['port'],
    aliases: ['端口'],
  },
  {
    path: 'deeplx.exe_path',
    segments: ['deeplx', 'exe_path'],
    title: 'DeepLX 可执行文件路径',
    note: 'DeepLX 可执行文件路径',
    type: 'string',
    widget: 'path',
    pathMode: 'file',
    fileSuffix: '.exe',
    default: 'deeplx_windows_amd64.exe',
    validators: ['fileExist'],
    warnOnly: true,
    aliases: ['可执行文件'],
  },
  {
    path: 'deeplx.api',
    segments: ['deeplx', 'api'],
    title: 'DeepLX API 地址',
    note: 'DeepLX API 地址',
    type: 'string',
    widget: 'text',
    default: 'http://127.0.0.1:1188/translate',
    validators: ['url'],
    aliases: ['翻译', '地址'],
  },
];

export const libretranslatePage: PageMeta = {
  id: 'libretranslate',
  title: 'LibreTranslate',
  icon: 'translate',
  sections: [{ id: 'general', title: '通用', fields: libretranslateFields }],
};

export const deeplxPage: PageMeta = {
  id: 'deeplx',
  title: 'DeepLX',
  icon: 'translate',
  sections: [{ id: 'general', title: '通用', fields: deeplxFields }],
};
