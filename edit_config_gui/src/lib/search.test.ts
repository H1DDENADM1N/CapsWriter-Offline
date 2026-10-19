import { beforeEach, describe, expect, it } from 'vitest';

import { fieldId } from './schema/index.ts';
import { SEARCH_LIMIT, landingSegments, searchAll, searchFields } from './search.ts';
import { configStore } from './stores/config.svelte.ts';

beforeEach(() => {
  configStore.__resetForTest();
});

describe('匹配方式', () => {
  it('中文子串命中', () => {
    expect(searchFields('端口').length).toBeGreaterThan(0);
  });

  it('拼音全拼命中', () => {
    expect(searchFields('duankou').some((h) => h.matchedBy === 'pinyin')).toBe(true);
  });

  it('首字母命中', () => {
    expect(searchFields('dk').some((h) => h.matchedBy === 'initial')).toBe(true);
  });

  it('段路径命中也算', () => {
    // server 与 client 两段都有 speech_recognition_port
    expect(searchFields('speech_recognition_port').length).toBeGreaterThanOrEqual(2);
  });

  it('标题同名词条按声明顺序稳定返回', () => {
    const first = searchFields('addr').map((h) => h.fieldId);
    const second = searchFields('addr').map((h) => h.fieldId);
    expect(first).toEqual(second);
  });

  it('空查询与纯空白返回空数组', () => {
    expect(searchFields('')).toEqual([]);
    expect(searchFields('   ')).toEqual([]);
  });

  it('分数降序', () => {
    const r = searchFields('addr');
    for (let i = 1; i < r.length; i += 1) {
      expect(r[i - 1]!.score).toBeGreaterThanOrEqual(r[i]!.score);
    }
  });
});

describe('多音字', () => {
  it('重叠的两种读法命中同一批结果', () => {
    const byChong = searchFields('fenduanchongdie').map((h) => h.fieldId);
    const byZhong = searchFields('fenduanzhongdie').map((h) => h.fieldId);

    expect(byChong.length).toBeGreaterThan(0);
    expect(byChong).toEqual(byZhong);
  });
});

describe('徽标与跳转', () => {
  it('隐藏字段仍进结果，带 hidden 徽标与 dependOn', () => {
    // 默认 enable_adb_control = false → adb_addr 被隐藏
    const hit = searchFields('adb_addr').find(
      (h) => h.segments.join('.') === 'client.adb_addr',
    );

    expect(hit).toBeTruthy();
    expect(hit!.badge).toBe('hidden');
    expect(hit!.dependOn).toEqual(['client', 'enable_adb_control']);
    expect(landingSegments(hit!)).toEqual(['client', 'enable_adb_control']);
  });

  it('派生只读键带 readonly 徽标与 derivedFrom', () => {
    const hit = searchFields('encoder_onnx_path').find(
      (h) => h.segments.join('.') === 'funasr_args.encoder_onnx_path',
    );

    expect(hit).toBeTruthy();
    expect(hit!.badge).toBe('readonly');
    expect(hit!.derivedFrom).toEqual(['model_paths', 'funasr_encoder_adaptor_path']);
    expect(landingSegments(hit!)).toEqual(['model_paths', 'funasr_encoder_adaptor_path']);
  });

  it('普通字段落回自己', () => {
    const hit = searchFields('speech_recognition_port')[0]!;
    expect(hit.badge).toBeUndefined();
    expect(landingSegments(hit)).toEqual(hit.segments);
  });
});

describe('动态表', () => {
  it('命中当前存在的进程名时补一条 dynamicKey 结果', () => {
    // 动态表在状态里是「一张表的行集合」，不是 4 段叶子：initialValues 会把
    // `…additional_special_apps.vlc.exe.name` 折叠进表 id 下的 rows
    configStore.setValue(fieldId(['client', 'additional_special_apps']), {
      'vlc.exe': { hotkey: 'ctrl + alt + f9', name: 'VLC Media Player' },
    });

    const hits = searchFields('vlc');
    const dyn = hits.find((h) => h.dynamicKey === 'vlc.exe');

    expect(dyn).toBeTruthy();
    expect(dyn!.segments.slice(0, 2)).toEqual(['client', 'additional_special_apps']);
  });

  it('没有该行时不会有动态命中', () => {
    expect(searchFields('notepad.exe').some((h) => h.dynamicKey !== undefined)).toBe(false);
  });
});

describe('命中结果携带 MD3 图标名', () => {
  it('普通字段使用为该配置项登记的图标', () => {
    expect(searchFields('adb_addr')[0]!.icon).toBe('wifi-tethering');
  });

  it('动态表条目沿用其所属字段的图标', () => {
    configStore.setValue(fieldId(['client', 'additional_special_apps']), {
      'vlc.exe': { name: 'VLC' },
    });

    const dyn = searchFields('vlc').find((h) => h.dynamicKey === 'vlc.exe');
    expect(dyn!.icon).toBe('apps');
  });
});

describe('secret 与截断', () => {
  it('secret 的值不参与匹配', () => {
    configStore.setValue(fieldId(['client', 'openai', 'api_key']), 'sk-abcdef');
    expect(searchFields('sk-abcdef')).toEqual([]);
  });

  it('结果截断到 50 条并暴露 truncated', () => {
    const all = searchAll('a');
    expect(all.truncated).toBe(true);
    expect(all.hits).toHaveLength(SEARCH_LIMIT);

    expect(searchFields('a').length).toBeLessThanOrEqual(SEARCH_LIMIT);
    expect(searchAll('adb_addr').truncated).toBe(false);
  });
});
