import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  allFields,
  derivedFields,
  editableFields,
  fieldId,
  pages,
} from './index.ts';

/**
 * schema ↔ config.toml ↔ schema_paths.json 的三方契约。
 *
 * 断言链的设计意图见 `edit_config_gui/scripts/gen-schema-paths.mjs` 的文件头。
 * 这里负责前半段（schema 与 JSON 同步），Rust 侧的
 * `edit_config_gui/src-tauri/tests/coverage.rs` 负责后半段（JSON 与真实
 * config.toml 同步）。
 */

const schemaPaths: string[][] = JSON.parse(
  readFileSync(
    // vitest 的环境是 jsdom，import.meta.url 是 http:// 而不是 file://，
    // 所以用进程 cwd（pnpm 始终在 edit_config_gui/ 下跑 vitest）
    resolve(process.cwd(), 'src-tauri/tests/schema_paths.json'),
    'utf8',
  ),
);

describe('schema 覆盖率', () => {
  it('14 页的 id 与顺序固定', () => {
    // 页 id / 顺序是 navStore.focus() 反查、Sidebar 顺序、PageView 的 about
    // 特判的共同依据，钉死防漂移
    expect(pages.map((p) => p.id)).toEqual([
      'server',
      'client',
      'aiProviders',
      'promptStyles',
      'additionalApps',
      'libretranslate',
      'deeplx',
      'modelPaths',
      'funasr',
      'sensevoice',
      'paraformer',
      'qwenCtc',
      'debug',
      'about',
    ]);
    expect(new Set(pages.map((p) => p.id)).size).toBe(14);
    expect(pages.every((p) => p.title.length > 0 && p.icon.length > 0)).toBe(
      true,
    );
  });

  it('可编辑固定键 170 + 派生只读 16 + 动态表 1 条描述 = 187', () => {
    // 188 个 TOML 叶子 − 2 条动态表条目 = 186；186 − 16 个派生只读 = 170。
    // allFields() 是 187 而不是 186，因为动态表在 schema 里占 1 条描述、
    // 却对应 TOML 里的 2 个条目。
    expect(editableFields().length).toBe(170);
    expect(derivedFields().length).toBe(16);
    expect(allFields().length).toBe(187);
  });

  it('schema 导出的 segments 与 schema_paths.json 完全一致', () => {
    const fromSchema = editableFields()
      .map((f) => f.segments)
      .sort((x, y) => (fieldId(x) < fieldId(y) ? -1 : 1));
    expect(schemaPaths.length).toBe(170);
    expect(fromSchema).toEqual(schemaPaths);
  });

  it('每个只读字段都带 derivedFrom，且来源键真实存在', () => {
    const all = allFields();
    const ids = new Set(all.map((f) => fieldId(f.segments)));
    for (const f of all.filter((x) => x.widget === 'readonly')) {
      expect(f.derivedFrom, `${f.path} 缺 derivedFrom`).toBeDefined();
      expect(
        ids.has(fieldId(f.derivedFrom!)),
        `${f.path} 的 derivedFrom 指向不存在的键`,
      ).toBe(true);
    }
  });

  it('segments 唯一（fieldId 不重复）', () => {
    const ids = allFields().map((f) => fieldId(f.segments));
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('title 非空且同段内唯一', () => {
    for (const page of pages) {
      for (const section of page.sections) {
        const titles = section.fields.map((f) => f.title);
        expect(titles.every((t) => t.trim().length > 0)).toBe(true);
        expect(new Set(titles).size).toBe(titles.length);
      }
    }
  });

  it('选项型控件的 default 必须落在 options 里', () => {
    for (const f of allFields()) {
      if (f.widget !== 'enum' || f.default === undefined) continue;
      const values = (f.options ?? []).map((o) => o.value);
      expect(
        values.includes(String(f.default)),
        `${f.path} 的 default=${String(f.default)} 不在 options 里`,
      ).toBe(true);
    }
  });

  it('每个 enum 控件都有非空 options', () => {
    for (const f of allFields()) {
      if (f.widget !== 'enum') continue;
      expect(f.options, `${f.path} 缺 options`).toBeDefined();
      expect(f.options!.length).toBeGreaterThan(0);
    }
  });

  it('path 控件必须声明 pathMode，且 file 模式要有后缀', () => {
    for (const f of allFields()) {
      if (f.widget !== 'path') continue;
      expect(f.pathMode, `${f.path} 缺 pathMode`).toBeDefined();
      if (f.pathMode === 'file') {
        expect(f.fileSuffix, `${f.path} 缺 fileSuffix`).toMatch(/^\./);
      }
    }
  });

  it('模型路径 20 个键全部 warnOnly（缺文件只警告不阻断）', () => {
    for (const f of allFields()) {
      if (f.segments[0] !== 'model_paths') continue;
      expect(f.warnOnly, `${f.path} 必须 warnOnly`).toBe(true);
      expect(f.validators?.length).toBeGreaterThan(0);
    }
  });

  it('只有 8 个多行提示词正文用 longText，且没有别的键允许换行', () => {
    const longText = allFields().filter((f) => f.widget === 'longText');
    expect(longText.length).toBe(8);
    for (const f of longText) {
      expect(f.segments[0]).toBe('client');
      expect(f.segments[1]).toBe('prompt_style');
      expect(f.path.startsWith('client.prompt_style.prompt_')).toBe(true);
      // 8 个正文键，不能是 *_shortcut
      expect(f.segments[2].endsWith('_shortcut')).toBe(false);
    }
  });

  it('allowEmpty 只出现在注释明说「留空」的键上', () => {
    // 逐个列出来而不是只数个数 —— 数量断言在加减字段时只会报「26 ≠ 25」，
    // 看不出到底哪一个键被顺走了。下面每一条都能在 config.toml 的注释里
    // 找到「留空则 …」或「空表示不使用」的依据。
    const expected = [
      // 「未配置 vscode_exe_path 则不启用 VSCode 跳转」
      'client.vscode_exe_path',
      // 4 个内置音乐播放器的全局暂停快捷键：「留空则 不暂停」
      'client.QQMusic_global_pause_hotkey',
      'client.CloudMusic_global_pause_hotkey',
      'client.PotPlayer_global_pause_hotkey',
      'client.foobar2000_global_pause_hotkey',
      // 两个 API Key + 兼容服务的 base_url（留空走官方默认）
      'client.openai.api_key',
      'client.openai.base_url',
      'client.zhipuai.api_key',
      // 8 个提示风格：正文留空则该风格不可用，快捷键留空则不绑定
      ...[
        'official',
        'sweetheart',
        'social',
        'poetry',
        'english',
        'academic',
        'customer_service',
        'creative_writing',
      ].flatMap((s) => [
        `client.prompt_style.prompt_${s}`,
        `client.prompt_style.prompt_${s}_shortcut`,
      ]),
      // 自定义规则文件：「留空表示不使用」
      'sensevoice_args.rule_fsts',
      'sensevoice_args.rule_fars',
      // QwenCTC 0.6B 拆分形态与 LLM 解码器：留空则退回上一种模式
      'model_paths.qwen_llm_path',
      'model_paths.qwen_ctc_encoder_frontend_path',
      'model_paths.qwen_ctc_encoder_backend_path',
    ].sort();

    const actual = allFields()
      .filter((f) => f.allowEmpty)
      .map((f) => f.path)
      .sort();
    expect(actual).toEqual(expected);
  });

  it('QwenCTC 十个新键的默认值、note 依据与页内相对顺序都钉死', () => {
    // Task 10 评审 I1：这三条规格原先没有任何断言 —— 删掉 note 里的
    // 「num_threads」、交换 frontend/backend、把 llm_n_ctx 默认值改掉，
    // 202 个测试仍然全绿。schema_paths.json 按 segments 字母序生成、Rust 用
    // BTreeSet 比较，所以「页内顺序」只有这里能护住；note 文本同理。
    const byPath = new Map(allFields().map((f) => [f.path, f]));

    // ① 默认值：模板里的值就是 GUI 输入框的初值
    expect(byPath.get('model_paths.qwen_llm_path')?.default).toBe(
      'models/qwen-ctc-aiinfra4/qwen3_asr_llm.q4_k.gguf',
    );
    expect(byPath.get('model_paths.qwen_ctc_encoder_frontend_path')?.default).toBe(
      '',
    );
    expect(byPath.get('model_paths.qwen_ctc_encoder_backend_path')?.default).toBe(
      '',
    );
    expect(byPath.get('qwen_ctc_args.enable_ctc')?.default).toBe(true);
    expect(byPath.get('qwen_ctc_args.llm_n_ctx')?.default).toBe(4096);
    expect(byPath.get('qwen_ctc_args.llm_n_threads')?.default).toBe(6);
    expect(byPath.get('qwen_ctc_args.llm_n_predict')?.default).toBe(256);

    // ② note 必须让用户看出「留空」的后果，以及 LLM 线程数与 ONNX 的无关
    for (const key of [
      'model_paths.qwen_llm_path',
      'model_paths.qwen_ctc_encoder_frontend_path',
      'model_paths.qwen_ctc_encoder_backend_path',
    ]) {
      expect(byPath.get(key)?.note, key).toContain('留空');
    }
    expect(byPath.get('qwen_ctc_args.llm_n_threads')?.note).toContain(
      'num_threads',
    );
    expect(byPath.get('qwen_ctc_args.enable_ctc')?.note).toContain('CTC');

    // ③ 页内相对顺序必须与 config.toml 的键序一致
    const pageOrder = (pageId: string) =>
      pages
        .find((p) => p.id === pageId)!
        .sections.flatMap((s) => s.fields)
        .map((f) => f.path);

    expect(pageOrder('modelPaths').filter((p) => p.startsWith('model_paths.qwen'))).toEqual([
      'model_paths.qwen_ctc_encoder_path',
      'model_paths.qwen_ctc_ctc_path',
      'model_paths.qwen_ctc_tokens_path',
      'model_paths.qwen_ctc_preprocessor_path',
      'model_paths.qwen_llm_path',
      'model_paths.qwen_ctc_encoder_frontend_path',
      'model_paths.qwen_ctc_encoder_backend_path',
    ]);

    expect(
      pageOrder('qwenCtc').map((p) => p.replace('qwen_ctc_args.', '')),
    ).toEqual([
      'encoder_onnx_path',
      'ctc_onnx_path',
      'tokens_path',
      'preprocessor_path',
      'decoder_gguf_path',
      'encoder_frontend_path',
      'encoder_backend_path',
      'blank_id',
      'unk_id',
      'mel_frames',
      'num_threads',
      'provider',
      'start_bias',
      'end_bias',
      'enable_ctc',
      'llm_n_ctx',
      'llm_n_threads',
      'llm_n_predict',
      'verbose',
    ]);
  });
});
