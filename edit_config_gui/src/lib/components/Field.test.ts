import { fireEvent, render, screen } from '@testing-library/svelte';
import { beforeEach, describe, expect, it } from 'vitest';

import { allFields, fieldId } from '../schema/index.ts';
import type { FieldMeta, SectionMeta } from '../schema/types.ts';
import { configStore } from '../stores/config.svelte.ts';
import { navStore } from '../stores/nav.svelte.ts';

import Field from './Field.svelte';
import Section from './Section.svelte';

function meta(p: Partial<FieldMeta>): FieldMeta {
  return {
    path: (p.segments ?? ['client', 'x']).join('.'),
    segments: ['client', 'x'],
    title: '测试字段',
    type: 'string',
    widget: 'text',
    validators: [],
    ...p,
  } as FieldMeta;
}

const adbField = meta({
  segments: ['client', 'adb_addr'],
  title: 'ADB 设备地址',
  validators: ['ipPort'],
  visibleWhen: { segments: ['client', 'enable_adb_control'], equals: true },
});

const addrField = meta({
  segments: ['server', 'addr'],
  title: '服务端监听地址',
  validators: ['localListenableIp'],
});

beforeEach(() => {
  configStore.__resetForTest();
  navStore.__resetForTest();
});

describe('Field 显隐', () => {
  it('visibleWhen 不满足时整行不渲染', () => {
    configStore.setValue(fieldId(['client', 'enable_adb_control']), false);
    const { queryByText } = render(Field, { field: adbField });
    expect(queryByText('ADB 设备地址')).toBeNull();
  });

  it('visibleWhen 满足时整行渲染', () => {
    configStore.setValue(fieldId(['client', 'enable_adb_control']), true);
    const { getByText } = render(Field, { field: adbField });
    expect(getByText('ADB 设备地址')).toBeTruthy();
  });

  it('visibleWhen 用 in 时按候选集合判断', () => {
    configStore.setValue(fieldId(['client', 'ai_provider']), 'zhipuai');
    const { queryByText } = render(Field, {
      field: meta({
        widget: 'text',
        segments: ['client', 'zhipuai', 'api_key'],
        title: '智谱 API Key',
        visibleWhen: { segments: ['client', 'ai_provider'], in: ['openai'] },
      }),
    });
    expect(queryByText('智谱 API Key')).toBeNull();
  });
});

describe('Field 状态显示', () => {
  it('有错误时渲染文案并标记 aria-invalid', () => {
    configStore.setError(fieldId(['server', 'addr']), '不是有效的IP地址');
    const { getByText, getByRole } = render(Field, { field: addrField });

    expect(getByText('不是有效的IP地址')).toBeTruthy();
    expect(getByRole('textbox').getAttribute('aria-invalid')).toBe('true');
  });

  it('脏字段显示「已修改」标记', () => {
    configStore.setValue(fieldId(['server', 'addr']), '127.0.0.1');
    const { getByText } = render(Field, { field: addrField });

    expect(getByText('已修改')).toBeTruthy();
  });

  it('未改动的字段不显示「已修改」', () => {
    configStore.setValue(fieldId(['server', 'addr']), '0.0.0.0');
    // 无基线时任何值都算脏；先造一个「基线 = 当前」的局面
    configStore.applyDoc({
      path: 'C:\\x\\config.toml',
      fingerprint: { mtimeMs: 1, size: 0, sha256: '' },
      baseDir: 'C:\\x',
      fields: [{ segments: ['server', 'addr'], value: '0.0.0.0', tomlType: 'string' }],
    });

    const { queryByText } = render(Field, { field: addrField });
    expect(queryByText('已修改')).toBeNull();
  });

  it('note 与 title 同时可见', () => {
    const withNote = meta({
      widget: 'text',
      segments: ['server', 'addr'],
      title: '服务端监听地址',
      note: '服务端启动时绑定的网卡地址，0.0.0.0 表示全部网卡',
    });

    const { getByText } = render(Field, { field: withNote });
    expect(getByText('服务端监听地址')).toBeTruthy();
    expect(getByText('服务端启动时绑定的网卡地址，0.0.0.0 表示全部网卡')).toBeTruthy();
  });
});

describe('Field 只读派生', () => {
  it('只读派生字段给出真实生效值与唯一一个跳转按钮', async () => {
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
    const field = allFields().find((f) => fieldId(f.segments) === fieldId(segments))!;
    expect(field).toBeDefined();

    const { getByText, container } = render(Field, { field });

    expect(container.textContent).toContain('此项由');
    expect(container.textContent).toContain('模型路径');

    await fireEvent.click(getByText(/跳转到「/));

    expect(navStore.current()).toBe('modelPaths');
    expect(navStore.highlight()).toBe(fieldId(['model_paths', 'funasr_llm_path']));
  });
});

describe('Section', () => {
  it('渲染标题、说明与全部字段', () => {
    const section: SectionMeta = {
      id: 'general',
      title: '通用',
      note: '这一段的说明',
      fields: [
        meta({ widget: 'text', segments: ['server', 'addr'], title: '字段甲' }),
        meta({ widget: 'bool', type: 'boolean', segments: ['server', 'only_run_once'], title: '字段乙' }),
      ],
    };

    render(Section, { section });

    expect(screen.getByText('通用')).toBeTruthy();
    expect(screen.getByText('这一段的说明')).toBeTruthy();
    expect(screen.getByText('字段甲')).toBeTruthy();
    expect(screen.getByText('字段乙')).toBeTruthy();
  });
});
