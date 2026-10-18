import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fieldId } from '../schema/index.ts';
import {
  buildPatches,
  buildRules,
  configStore,
  defaultOf,
  initialValues,
  isVisible,
} from './config.svelte.ts';
import { navStore } from './nav.svelte.ts';
import { toast } from './toast.svelte.ts';

const id = (...parts: string[]): string => fieldId(parts);

describe('补丁生成', () => {
  it('只产出脏字段，kind 来自 schema 而非值本身', () => {
    const base = { [id('server', 'addr')]: '0.0.0.0', [id('server', 'model')]: 'FunASR' };
    const cur = { [id('server', 'addr')]: '127.0.0.1', [id('server', 'model')]: 'FunASR' };

    const p = buildPatches(base, cur);
    expect(p).toHaveLength(1);
    expect(p[0].segments).toEqual(['server', 'addr']);
    expect(p[0].value).toEqual({ kind: 'str', value: '127.0.0.1' });
  });

  it('字符串型的数字键仍发 str', () => {
    const key = id('client', 'start_music_volume');
    const p = buildPatches({ [key]: '100' }, { [key]: '80' });
    expect(p[0].value).toEqual({ kind: 'str', value: '80' });
  });

  it('整数键发 int，浮点键发 float', () => {
    const dur = id('client', 'mic_seg_duration');
    const thr = id('client', 'threshold');

    const p = buildPatches({ [dur]: 60, [thr]: 0.5 }, { [dur]: 120, [thr]: 0.75 });
    expect(p).toEqual([
      { segments: ['client', 'mic_seg_duration'], value: { kind: 'int', value: 120 } },
      { segments: ['client', 'threshold'], value: { kind: 'float', value: 0.75 } },
    ]);
  });

  it('真假布尔发 bool', () => {
    const key = id('client', 'hold_mode');
    expect(buildPatches({ [key]: false }, { [key]: true })[0].value).toEqual({
      kind: 'bool',
      value: true,
    });
  });

  it('二元组数组发 pairArray', () => {
    const key = id('client', 'enter_apps');
    const p = buildPatches(
      { [key]: [['happ.exe', 0.5]] },
      { [key]: [['happ.exe', 0.3], ['hexin.exe', 0.5]] },
    );
    expect(p[0].value).toEqual({
      kind: 'pairArray',
      value: [
        ['happ.exe', 0.3],
        ['hexin.exe', 0.5],
      ],
    });
  });

  it('派生只读键永不产生补丁', () => {
    const key = id('funasr_args', 'encoder_onnx_path');
    const p = buildPatches(
      { [key]: '${model_paths.funasr_encoder_adaptor_path}' },
      { [key]: 'models/别的地方.onnx' },
    );
    expect(p).toEqual([]);
  });

  it('动态表：新增/改动发 tableRow，删除发 delete，且删除排在后面', () => {
    const key = id('client', 'additional_special_apps');
    const base = {
      [key]: {
        'vlc.exe': { name: 'VLC', hotkey: 'ctrl + alt + m' },
        'old.exe': { name: '旧', hotkey: '' },
      },
    };
    const cur = {
      [key]: {
        'vlc.exe': { name: 'VLC 播放器', hotkey: 'ctrl + alt + m' },
        'pot.exe': { name: 'Pot', hotkey: '' },
      },
    };

    const p = buildPatches(base, cur);
    expect(p.map((x) => [x.segments.join('/'), x.value.kind])).toEqual([
      ['client/additional_special_apps/vlc.exe', 'tableRow'],
      ['client/additional_special_apps/pot.exe', 'tableRow'],
      ['client/additional_special_apps/old.exe', 'delete'],
    ]);
    // 整行下发，漏列会被 Rust 当删除
    expect(p[0].value).toEqual({
      kind: 'tableRow',
      value: { name: 'VLC 播放器', hotkey: 'ctrl + alt + m' },
    });
  });
});

describe('规则下发', () => {
  it('不可见字段不下发规则', () => {
    const values = { [id('client', 'enable_adb_control')]: false };
    const rules = buildRules(values);
    expect(rules.some((r) => r.segments.join('.') === 'client.adb_addr')).toBe(false);
  });

  it('可见字段会下发规则，且 allowEmpty / warnOnly 原样透传', () => {
    // pause_other_audio 打开后，4 个「全局暂停」快捷键才可见
    const values = {
      [id('client', 'enable_adb_control')]: true,
      [id('client', 'pause_other_audio')]: true,
    };
    const rules = buildRules(values);

    const adb = rules.find((r) => r.segments.join('.') === 'client.adb_addr');
    expect(adb?.validators).toEqual(['ipPort']);

    // model_paths 全部只警告不阻断（模型动辄几 GB，常先改配置后下模型）
    const model = rules.find((r) => r.segments.join('.') === 'model_paths.funasr_llm_path');
    expect(model?.warnOnly).toBe(true);
    expect(model?.fileSuffix).toBe('.gguf');

    // 四个「留空则不暂停」的快捷键必须允许空串
    const pause = rules.find(
      (r) => r.segments.join('.') === 'client.QQMusic_global_pause_hotkey',
    );
    expect(pause?.allowEmpty).toBe(true);
  });

  it('visibleWhen 用值判断，不猜段名', () => {
    const values = { [id('server', 'model')]: 'Sensevoice' };
    const rules = buildRules(values);
    // format_punc 只在 Paraformer 下可见
    expect(rules.some((r) => r.segments.join('.') === 'server.format_punc')).toBe(false);
  });
});

describe('初始值', () => {
  it('int 字段接受超范围既有值，不做夹取', () => {
    const v = initialValues([
      { segments: ['client', 'mic_seg_duration'], value: 120 },
    ]);
    expect(v[id('client', 'mic_seg_duration')]).toBe(120);
  });

  it('动态表叶子被折叠成行对象', () => {
    const v = initialValues([
      { segments: ['client', 'additional_special_apps', 'vlc.exe', 'name'], value: 'VLC' },
      {
        segments: ['client', 'additional_special_apps', 'vlc.exe', 'hotkey'],
        value: 'ctrl + alt + m',
      },
    ]);
    // 行键里的点属于键本身，不能被当成层级拆开
    expect(v[id('client', 'additional_special_apps')]).toEqual({
      'vlc.exe': { name: 'VLC', hotkey: 'ctrl + alt + m' },
    });
  });

  it('文档里缺的键补 schema 默认值', () => {
    const v = initialValues([]);
    expect(v[id('server', 'model')]).toBe('FunASR');
    expect(v[id('client', 'enable_adb_control')]).toBe(false);
  });

  it('没有 default 的字段给类型零值', () => {
    const meta = {
      path: 'x.y',
      segments: ['x', 'y'],
      title: 'x',
      type: 'string' as const,
      widget: 'text' as const,
    };
    expect(defaultOf(meta)).toBe('');
  });
});

describe('可见性', () => {
  it('未声明 visibleWhen 的字段恒可见', () => {
    const meta = {
      path: 'server.addr',
      segments: ['server', 'addr'],
      title: 'addr',
      type: 'string' as const,
      widget: 'text' as const,
    };
    expect(isVisible(meta, {})).toBe(true);
  });
});

describe('脏态跟踪', () => {
  beforeEach(() => configStore.__resetForTest());

  it('改字段后进脏集合，改回原值后自动移出', () => {
    const key = id('server', 'addr');
    expect(configStore.dirtyIds().has(key)).toBe(false);

    configStore.setValue(key, '127.0.0.1');
    expect(configStore.dirtyIds().has(key)).toBe(true);
    expect(configStore.patches()).toHaveLength(1);

    // 改回原值 —— 脏集合必须自己收缩，不能靠用户点「放弃」
    configStore.setValue(key, '0.0.0.0');
    expect(configStore.dirtyIds().has(key)).toBe(false);
    expect(configStore.patches()).toEqual([]);
  });

  it('revert_all：放弃后 current 回到 original，脏集合与错误表都清空', () => {
    const key = id('server', 'addr');
    configStore.setValue(key, '1.2.3.4');
    configStore.setError(key, '不是有效的IP地址');
    expect(configStore.errorOf(key)).toBe('不是有效的IP地址');

    configStore.resetAll();
    expect(configStore.dirtyIds().size).toBe(0);
    expect(configStore.values()[key]).toBe('0.0.0.0');
    expect(configStore.errorOf(key)).toBeUndefined();
  });

  it('revert_field：单字段恢复默认只动该字段，其它脏字段保持脏', () => {
    const a = id('server', 'addr');
    const m = id('server', 'model');
    configStore.setValue(a, '1.2.3.4');
    configStore.setValue(m, 'Sensevoice');

    configStore.resetValue(a);
    expect(configStore.values()[a]).toBe('0.0.0.0'); // 回到 schema default
    expect(configStore.dirtyIds().has(a)).toBe(false);
    expect(configStore.dirtyIds().has(m)).toBe(true); // 另一个仍脏
  });

  it('编辑某字段会清掉它上一轮的错误', () => {
    const key = id('server', 'addr');
    configStore.setError(key, '不是有效的IP地址');
    configStore.setValue(key, '10.0.0.1');
    expect(configStore.errorOf(key)).toBeUndefined();
  });

  it('applyProblems 按 Rust 的分流结果落库，不做二次判断', () => {
    configStore.applyProblems({
      errors: [{ segments: ['server', 'addr'], message: '不是有效的本地可监听IP地址' }],
      warnings: [{ segments: ['model_paths', 'funasr_llm_path'], message: '文件不存在' }],
    });

    expect(configStore.errorOf(id('server', 'addr'))).toBe('不是有效的本地可监听IP地址');
    // 只警告的项绝不能进 errors，否则「模型缺失」会退化成阻断保存
    expect(configStore.errorOf(id('model_paths', 'funasr_llm_path'))).toBeUndefined();
    expect(configStore.warnings()).toHaveLength(1);
  });

  it('applyDoc 用文档叶子重建基线，改动全部作废', () => {
    configStore.setValue(id('server', 'addr'), '9.9.9.9');

    configStore.applyDoc({
      path: 'C:\\x\\config.toml',
      fingerprint: { mtimeMs: 1, size: 2, sha256: 'ab' },
      baseDir: 'C:\\x',
      fields: [{ segments: ['server', 'addr'], value: '10.1.1.1', tomlType: 'string' }],
    });

    expect(configStore.state()).toBe('ready');
    expect(configStore.values()[id('server', 'addr')]).toBe('10.1.1.1');
    expect(configStore.dirtyIds().size).toBe(0);
    expect(configStore.path()).toBe('C:\\x\\config.toml');
  });
});

describe('导航', () => {
  beforeEach(() => navStore.__resetForTest());

  it('focus 按字段反查页 id，不能靠 segments[0] 猜', () => {
    // client.zhipuai 属于「AI 模型」页，不是 client 页
    navStore.focus(['client', 'zhipuai', 'model']);
    expect(navStore.current()).toBe('aiProviders');
    expect(navStore.highlight()).toBe(id('client', 'zhipuai', 'model'));

    // prompt_style 的 16 个键在独立页
    navStore.focus(['client', 'prompt_style', 'prompt_official']);
    expect(navStore.current()).toBe('promptStyles');

    // 真正的 client 主表键才落在 client 页
    navStore.focus(['client', 'addr']);
    expect(navStore.current()).toBe('client');
  });

  it('高亮 1.5 秒后自动消失', () => {
    vi.useFakeTimers();
    try {
      navStore.focus(['server', 'addr']);
      expect(navStore.highlight()).not.toBeNull();

      vi.advanceTimersByTime(1499);
      expect(navStore.highlight()).not.toBeNull();

      vi.advanceTimersByTime(1);
      expect(navStore.highlight()).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('连续 focus 时前一次的定时器不得把新高亮清掉', () => {
    vi.useFakeTimers();
    try {
      navStore.focus(['server', 'addr']);
      vi.advanceTimersByTime(1000);

      navStore.focus(['server', 'model']);
      vi.advanceTimersByTime(1000); // 距第一次已 2000ms，但第二次只过了 1000ms

      expect(navStore.highlight()).toBe(id('server', 'model'));

      vi.advanceTimersByTime(500);
      expect(navStore.highlight()).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it('切页会清掉残留高亮', () => {
    navStore.focus(['server', 'addr']);
    navStore.go('client');
    expect(navStore.current()).toBe('client');
    expect(navStore.highlight()).toBeNull();
  });
});

describe('提示队列', () => {
  beforeEach(() => toast.__resetForTest());

  it('push 入队，dismiss 出队', () => {
    const a = toast.push('success', '已保存');
    toast.push('warn', '模型文件不存在');
    expect(toast.items().map((t) => t.message)).toEqual(['已保存', '模型文件不存在']);

    toast.dismiss(a);
    expect(toast.items().map((t) => t.message)).toEqual(['模型文件不存在']);
  });

  it('error 常驻，info 自动消失', () => {
    vi.useFakeTimers();
    try {
      toast.push('error', '保存失败');
      toast.push('info', '已复制路径');

      vi.advanceTimersByTime(3000);
      expect(toast.items().map((t) => t.kind)).toEqual(['error']);

      vi.advanceTimersByTime(60000);
      expect(toast.items().map((t) => t.kind)).toEqual(['error']);
    } finally {
      vi.useRealTimers();
    }
  });
});
