import { describe, expect, it } from 'vitest';

import { FIELD_ICONS, ICONS, FALLBACK_SAMPLE, iconForField } from './fieldIcons.ts';
import { allFields } from './schema/index.ts';

/**
 * 图标表的护栏。
 *
 * 配置项是「数据驱动」的：加一个字段只改 schema，界面自动多一行。图标是唯一
 * 需要人工逐条指定的东西，所以这里的断言就围绕「有没有漏、有没有写错名字」：
 *  - 每一项都登记了图标（不允许靠兜底混过去，否则界面会出现一堆一模一样的图形）
 *  - 映射里没有指向已删除字段的陈旧键
 *  - 名字都真的在 `ICONS` 里注册过（拼错 `auto-aweseom` 这种当场变红）
 */
describe('fieldIcons', () => {
  const fields = allFields();
  const paths = new Set(fields.map((f) => f.path));

  it('每个配置项都有专属图标', () => {
    const missing = fields.filter((f) => !(f.path in FIELD_ICONS)).map((f) => f.path);
    expect(missing).toEqual([]);
  });

  it('没有指向已删除字段的陈旧图标', () => {
    const stale = Object.keys(FIELD_ICONS).filter((p) => !paths.has(p));
    expect(stale).toEqual([]);
  });

  it('映射里的图标名都在登记表里', () => {
    const unknown = [...new Set(Object.values(FIELD_ICONS))].filter((n) => !(n in ICONS));
    expect(unknown).toEqual([]);
  });

  it('登记表里没有多余的图标', () => {
    const used = new Set(Object.values(FIELD_ICONS));
    const unused = Object.keys(ICONS).filter((n) => !used.has(n) && !FALLBACK_SAMPLE.includes(n));
    expect(unused).toEqual([]);
  });

  it('每个登记项都是可渲染的 Iconify 数据', () => {
    for (const [name, icon] of Object.entries(ICONS)) {
      expect(icon, name).toMatchObject({ width: expect.any(Number), height: expect.any(Number) });
      expect(typeof icon.body, name).toBe('string');
      expect(icon.body, name).toContain('<path');
    }
  });

  it('iconForField 对每一项都能给出图标', () => {
    for (const field of fields) {
      const icon = iconForField(field);
      expect(icon, field.path).toBe(ICONS[FIELD_ICONS[field.path]]);
    }
  });

  it('未登记的字段按控件类型兜底', () => {
    expect(iconForField({ path: '不存在的键', widget: 'bool' })).toBe(ICONS['toggle-on']);
    expect(iconForField({ path: '不存在的键', widget: 'path' })).toBe(ICONS.folder);
  });
});
