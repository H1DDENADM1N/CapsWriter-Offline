import { fireEvent, render, screen } from '@testing-library/svelte';
import { describe, expect, it } from 'vitest';

import type { FieldMeta, JsonValue } from '../../schema/types.ts';
import { allFields, fieldId } from '../../schema/index.ts';
import { configStore } from '../../stores/config.svelte.ts';

import BoolWidget from './BoolWidget.svelte';
import DynamicTableWidget from './DynamicTableWidget.svelte';
import EnumWidget from './EnumWidget.svelte';
import HotkeyWidget from './HotkeyWidget.svelte';
import IntWidget from './IntWidget.svelte';
import ReadonlyWidget from './ReadonlyWidget.svelte';
import SecretWidget from './SecretWidget.svelte';
import StringListWidget from './StringListWidget.svelte';
import TextWidget from './TextWidget.svelte';
import { widgetFor } from './index.ts';

/** 测试用字段工厂：只覆盖需要的字段，其余给安全默认值 */
function f(p: Partial<FieldMeta> & { widget: FieldMeta['widget'] }): FieldMeta {
  return {
    path: (p.segments ?? ['client', 'x']).join('.'),
    segments: ['client', 'x'],
    title: '测试字段',
    type: 'string',
    validators: [],
    ...p,
  } as FieldMeta;
}

describe('基础控件', () => {
  it('text 控件透传输入', async () => {
    const got: unknown[] = [];
    const { getByRole } = render(TextWidget, {
      field: f({ widget: 'text' }),
      value: 'a',
      onChange: (v: JsonValue) => got.push(v),
    });
    await fireEvent.input(getByRole('textbox'), { target: { value: 'abc' } });
    expect(got.at(-1)).toBe('abc');
  });

  it('bool 控件上报布尔值', async () => {
    const got: unknown[] = [];
    const { getByRole } = render(BoolWidget, {
      field: f({ widget: 'bool', type: 'boolean' }),
      value: false,
      onChange: (v: JsonValue) => got.push(v),
    });
    await fireEvent.click(getByRole('checkbox'));
    expect(got.at(-1)).toBe(true);
  });

  it('secret 控件的明文不进无障碍名称', () => {
    const secret = 'sk-不该出现-1234';
    const { container } = render(SecretWidget, {
      field: f({ widget: 'secret', title: 'API Key' }),
      value: secret,
      onChange: () => {},
    });

    const input = container.querySelector('input') as HTMLInputElement;
    expect(input.type).toBe('password');
    expect(input.getAttribute('aria-label')).toBe('API Key');
    expect(input.getAttribute('title')).toBeNull();
  });

  it('enum 控件保留不在候选内的当前值', () => {
    const { getByRole } = render(EnumWidget, {
      field: f({ widget: 'enum', options: [{ value: 'a', label: 'A' }, { value: 'b', label: 'B' }] }),
      value: 'zzz',
      onChange: () => {},
    });

    const select = getByRole('combobox') as HTMLSelectElement;
    expect(select.value).toBe('zzz');
  });
});

describe('数值控件', () => {
  it('int 控件编辑时夹取到 min/max', async () => {
    const got: number[] = [];
    const { getByRole } = render(IntWidget, {
      field: f({ widget: 'int', type: 'integer', min: 10, max: 60 }),
      value: 20,
      onChange: (v: JsonValue) => got.push(v as number),
    });

    await fireEvent.change(getByRole('spinbutton'), { target: { value: '999' } });
    expect(got.at(-1)).toBe(60);
  });

  it('int 控件首次渲染不改写超范围既有值', () => {
    const { getByRole } = render(IntWidget, {
      field: f({ widget: 'int', type: 'integer', min: 10, max: 60 }),
      value: 120,
      onChange: () => {},
    });

    expect((getByRole('spinbutton') as HTMLInputElement).value).toBe('120');
  });

  it('int 控件对字符串型整数键上报字符串', async () => {
    const got: unknown[] = [];
    const { getByRole } = render(IntWidget, {
      field: f({ widget: 'int', type: 'string', min: 0, max: 100 }),
      value: '100',
      onChange: (v: JsonValue) => got.push(v),
    });

    await fireEvent.change(getByRole('spinbutton'), { target: { value: '50' } });
    expect(got.at(-1)).toBe('50');
  });
});

describe('快捷键控件', () => {
  it('hotkey 控件录制后回填', async () => {
    const got: string[] = [];
    const { getByRole } = render(HotkeyWidget, {
      field: f({ widget: 'hotkey' }),
      value: '',
      onChange: (v: JsonValue) => got.push(v as string),
    });

    await fireEvent.click(getByRole('button', { name: /录制/ }));
    await fireEvent.keyDown(window, { key: 'F5', ctrlKey: true, altKey: true });
    expect(got.at(-1)).toBe('ctrl + alt + f5');
  });

  it('hotkey 录制 Esc 只退出不写值', async () => {
    const got: unknown[] = [];
    const { getByRole } = render(HotkeyWidget, {
      field: f({ widget: 'hotkey' }),
      value: '',
      onChange: (v: JsonValue) => got.push(v),
    });

    await fireEvent.click(getByRole('button', { name: /录制/ }));
    await fireEvent.keyDown(window, { key: 'Escape' });
    expect(got).toHaveLength(0);
  });

  it('hotkey 录制方向键时用 Python 的规范名', async () => {
    const got: string[] = [];
    const { getByRole } = render(HotkeyWidget, {
      field: f({ widget: 'hotkey' }),
      value: '',
      onChange: (v: JsonValue) => got.push(v as string),
    });

    await fireEvent.click(getByRole('button', { name: /录制/ }));
    await fireEvent.keyDown(window, { key: 'ArrowUp', ctrlKey: true });
    expect(got.at(-1)).toBe('ctrl + up');
  });
});

describe('列表控件', () => {
  it('stringList 把 [""] 显示成空列表', () => {
    render(StringListWidget, {
      field: f({ widget: 'stringList', type: 'stringArray' }),
      value: [''],
      onChange: () => {},
    });

    expect(screen.getByText('暂未添加')).toBeTruthy();
  });

  it('stringList 删除空白项后才上报', async () => {
    const got: unknown[] = [];
    const { getByRole } = render(StringListWidget, {
      field: f({ widget: 'stringList', type: 'stringArray' }),
      value: ['happ.exe'],
      onChange: (v: JsonValue) => got.push(v),
    });

    await fireEvent.click(getByRole('button', { name: /添加一项/ }));
    expect(got.at(-1)).toEqual(['happ.exe']);
  });
});

describe('动态表控件', () => {
  it('改一行时上报整表，不整表替换', async () => {
    const got: unknown[] = [];
    const { getByLabelText } = render(DynamicTableWidget, {
      field: f({ widget: 'dynamicTable', type: 'inlineTable', segments: ['client', 'additional_special_apps'] }),
      value: {
        'vlc.exe': { hotkey: 'ctrl + alt + f9', name: 'VLC Media Player' },
      },
      onChange: (v: JsonValue) => got.push(v),
    });

    await fireEvent.input(getByLabelText('显示名称 第 1 项'), { target: { value: 'VLC' } });
    expect(got.at(-1)).toEqual({ 'vlc.exe': { hotkey: 'ctrl + alt + f9', name: 'VLC' } });
  });

  it('进程名大小写原样保留', async () => {
    const got: unknown[] = [];
    const { getByLabelText } = render(DynamicTableWidget, {
      field: f({ widget: 'dynamicTable', type: 'inlineTable', segments: ['client', 'additional_special_apps'] }),
      value: {},
      onChange: (v: JsonValue) => got.push(v),
    });

    await fireEvent.click(screen.getByRole('button', { name: /添加一行/ }));
    await fireEvent.input(getByLabelText('进程名 第 1 项'), { target: { value: '  PotPlayerMini64.exe  ' } });
    expect(Object.keys(got.at(-1) as Record<string, unknown>)).toEqual(['PotPlayerMini64.exe']);
  });
});

describe('只读派生控件', () => {
  it('显示 model_paths 里的真实值，而不是占位符', () => {
    configStore.__resetForTest();
    configStore.applyDoc({
      path: 'C:\\x\\config.toml',
      fingerprint: { mtimeMs: 1, size: 0, sha256: '' },
      baseDir: 'C:\\x',
      fields: [
        {
          segments: ['model_paths', 'funasr_llm_path'],
          value: 'models/Fun-ASR-Nano/Decoder.q8_0.gguf',
          tomlType: 'string',
        },
        {
          segments: ['funasr_args', 'decoder_gguf_path'],
          value: '${model_paths.funasr_llm_path}',
          tomlType: 'string',
        },
      ],
    });

    const segments = ['funasr_args', 'decoder_gguf_path'];
    const field = allFields().find((x) => fieldId(x.segments) === fieldId(segments));
    expect(field).toBeDefined();
    expect(field!.derivedFrom).toEqual(['model_paths', 'funasr_llm_path']);

    const { container } = render(ReadonlyWidget, {
      field: field!,
      value: '${model_paths.funasr_llm_path}',
      onChange: () => {},
    });

    const code = container.querySelectorAll('code');
    expect(code[0].textContent).toContain('Decoder.q8_0.gguf');
    // 占位符只作为「文件里存着的原值」出现在说明里，不是可编辑内容
    expect(code[1].textContent).toBe('${model_paths.funasr_llm_path}');
  });
});

describe('注册表', () => {
  it('schema 里用到的 widget 全部接线', () => {
    for (const meta of allFields()) {
      expect(widgetFor(meta.widget)).toBeTruthy();
    }
  });
});
