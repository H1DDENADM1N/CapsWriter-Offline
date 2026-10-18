import type { PageMeta } from './types.ts';

/**
 * 动态表：`client.additional_special_apps`。
 *
 * 这个键的内容不是固定字段，而是 `"<进程名>" = { hotkey = "...", name = "..." }`
 * 任意多条。所以它在 schema 里只有**一条**描述，`segments` 到表为止；
 * 具体条目由运行时从文档里读出（见 `DynamicTableWidget`）。
 *
 * 两个不能动的语义（都在 `util/client/pause_other_audio.py` 里）：
 * - 进程名是**字典键精确匹配、大小写敏感**（`if exe_name in special_apps_map`），
 *   而内置四项的键长这样：`QQMusic.exe` / `CloudMusic.exe` /
 *   `PotPlayerMini64.exe` / `foobar2000.exe`。所以保存时必须原样保留用户写的
 *   大小写，不能「顺手归一化成小写」——归一化后就匹配不上了。
 * - 快捷键留空 = 该应用不暂停（`pause_other_audio.py:119-130`）。
 *
 * 保存时**不能整表重建**（会丢掉每行的行尾注释），必须逐项 insert/remove，
 * 见规格 §9.5 与实际测试 `dynamic_table_row_update_keeps_trailing_comment`。
 */
export const additionalAppsPage: PageMeta = {
  id: 'additionalApps',
  title: '附加特殊应用',
  icon: 'app',
  sections: [
    {
      id: 'apps',
      title: '特殊应用列表',
      note: [
        '除了 QQ音乐、网易云音乐、PotPlayer、foobar2000 之外，还想让别的程序',
        '在录音时被暂停播放，就在这里登记它自己设置的「全局 播放/暂停」快捷键。',
        '进程名要和任务管理器里看到的完全一致（大小写敏感）。快捷键留空表示不暂停。',
      ].join(''),
      fields: [
        {
          // 只有一条描述，不代表一个叶子键；动态条目由运行时展开
          path: 'client.additional_special_apps',
          segments: ['client', 'additional_special_apps'],
          title: '特殊应用列表',
          type: 'inlineTable',
          widget: 'dynamicTable',
          aliases: ['特殊应用', '暂停', '音乐', 'vlc'],
        },
      ],
    },
  ],
};
