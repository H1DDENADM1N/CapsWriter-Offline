/**
 * 保存流程的用例。
 *
 * 全部走 mock 的 bridge：这一层要验证的是「状态怎么流转」，真正的写盘、
 * 冲突检测、回滚已在 `src-tauri/src/file_io.rs` 与 `commands.rs` 的测试里覆盖。
 *
 * `vi.hoisted` 而不是在工厂里直接读外层 `const`：`vi.mock` 会被提升到 import
 * 之前，那时外层的 `const` 还处于 TDZ，写进去就是
 * `Cannot access 'previewSave' before initialization`。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  openConfig: vi.fn(),
  reloadConfig: vi.fn(),
  previewSave: vi.fn(),
  commitSave: vi.fn(),
  pickPath: vi.fn(),
  runningProcesses: vi.fn(),
  restartService: vi.fn(),
}));

vi.mock('../../bridge.ts', () => ({ bridge: mocks }));

import type { FileFingerprint, PreviewResult } from '../../bridge.ts';
import { fieldId } from '../schema/index.ts';
import { configStore } from '../stores/config.svelte.ts';
import { saveStore } from '../stores/save.svelte.ts';

const FP: FileFingerprint = { mtimeMs: 1, size: 2, sha256: 'aa' };
const SEGS = ['server', 'addr'];
const ADDR = fieldId(SEGS);

function openDoc(addr = '0.0.0.0'): void {
  configStore.applyDoc({
    path: 'config.toml',
    fingerprint: FP,
    baseDir: '.',
    fields: [{ segments: SEGS, value: addr, tomlType: 'string' }],
  });
}

function previewOk(over: Partial<PreviewResult> = {}): PreviewResult {
  return {
    diff: '--- config.toml\n+++ config.toml\n-addr = "0.0.0.0"\n+addr = "127.0.0.1"\n',
    errors: [],
    warnings: [],
    changed: [SEGS],
    ...over,
  };
}

beforeEach(() => {
  for (const fn of Object.values(mocks)) fn.mockReset();
  configStore.__resetForTest();
  saveStore.cancel();
  openDoc();
  configStore.setValue(ADDR, '127.0.0.1');
});

describe('saveStore', () => {
  it('预览会调用 preview_save，成功后进入 confirm 态', async () => {
    mocks.previewSave.mockResolvedValue(previewOk());

    await saveStore.preview();

    expect(mocks.previewSave).toHaveBeenCalledOnce();
    const [patches, rules] = mocks.previewSave.mock.calls[0];
    expect(patches).toEqual([{ segments: SEGS, value: { kind: 'str', value: '127.0.0.1' } }]);
    expect(Array.isArray(rules)).toBe(true);
    expect(saveStore.phase().kind).toBe('confirm');
    expect(mocks.commitSave).not.toHaveBeenCalled();
  });

  it('没有改动时不调后端', async () => {
    configStore.resetAll();

    await saveStore.preview();

    expect(mocks.previewSave).not.toHaveBeenCalled();
    expect(saveStore.phase().kind).toBe('idle');
  });

  it('预览返回错误时不进入确认态，错误落到字段上', async () => {
    mocks.previewSave.mockResolvedValue(
      previewOk({ errors: [{ segments: SEGS, message: '不是有效的IP地址' }] }),
    );

    await saveStore.preview();

    expect(saveStore.phase().kind).toBe('idle');
    expect(configStore.errorOf(ADDR)).toBe('不是有效的IP地址');
  });

  it('只有 warnings 时仍可确认保存，警告带进对话框', async () => {
    mocks.previewSave.mockResolvedValue(
      previewOk({ warnings: [{ segments: SEGS, message: '文件不存在' }] }),
    );

    await saveStore.preview();

    const phase = saveStore.phase();
    expect(phase.kind).toBe('confirm');
    if (phase.kind === 'confirm') {
      expect(phase.result.warnings).toHaveLength(1);
    }
    expect(configStore.errors()).toEqual({});
  });

  it('提交后拿到新指纹、备份路径，脏集合清空', async () => {
    const FP2: FileFingerprint = { mtimeMs: 9, size: 9, sha256: 'bb' };
    mocks.previewSave.mockResolvedValue(previewOk());
    mocks.commitSave.mockResolvedValue({
      fingerprint: FP2,
      backupPath: 'C:/repo/config.toml.bak',
    });

    await saveStore.preview();
    await saveStore.confirm(false);

    expect(mocks.commitSave).toHaveBeenCalledWith(expect.any(Array), expect.any(Array), FP, false);
    const phase = saveStore.phase();
    expect(phase.kind).toBe('done');
    if (phase.kind === 'done') expect(phase.backupPath).toBe('C:/repo/config.toml.bak');

    expect(configStore.patches()).toEqual([]);
    expect(configStore.dirtyCount()).toBe(0);
    expect(configStore.fingerprint()).toEqual(FP2);
  });

  it('CONFLICT 时进入冲突态且不自动重试；强制覆盖才带 force=true 重发', async () => {
    mocks.previewSave.mockResolvedValue(previewOk());
    mocks.commitSave.mockRejectedValue('CONFLICT');

    await saveStore.preview();
    await saveStore.confirm(false);

    // reject 的是字符串本身而不是 Error，用 Error.message 判会漏掉
    expect(saveStore.phase().kind).toBe('conflict');
    expect(mocks.commitSave).toHaveBeenCalledTimes(1);
    expect(mocks.reloadConfig).not.toHaveBeenCalled();

    mocks.commitSave.mockResolvedValue({ fingerprint: FP, backupPath: 'x.bak' });
    await saveStore.confirm(true);

    expect(mocks.commitSave).toHaveBeenLastCalledWith(
      expect.any(Array),
      expect.any(Array),
      FP,
      true,
    );
    expect(saveStore.phase().kind).toBe('done');
  });

  it('冲突时选择重新加载会丢弃内存改动', async () => {
    mocks.previewSave.mockResolvedValue(previewOk());
    mocks.commitSave.mockRejectedValue('CONFLICT');
    mocks.reloadConfig.mockResolvedValue({
      path: 'config.toml',
      fingerprint: FP,
      baseDir: '.',
      fields: [{ segments: SEGS, value: '0.0.0.0', tomlType: 'string' }],
    });

    await saveStore.preview();
    await saveStore.confirm(false);
    await saveStore.reloadAndReset();

    expect(mocks.reloadConfig).toHaveBeenCalledOnce();
    expect(saveStore.phase().kind).toBe('idle');
    expect(configStore.dirtyCount()).toBe(0);
    expect(configStore.patches()).toEqual([]);
  });

  it('写盘失败进入 failed 态并原样保留后端文案', async () => {
    mocks.previewSave.mockResolvedValue(previewOk());
    mocks.commitSave.mockRejectedValue('拒绝访问。 (os error 5)');

    await saveStore.preview();
    await saveStore.confirm(false);

    const phase = saveStore.phase();
    expect(phase.kind).toBe('failed');
    if (phase.kind === 'failed') expect(phase.error).toBe('拒绝访问。 (os error 5)');
    // 失败不能顺手把脏标记清掉，用户还得重试
    expect(configStore.dirtyCount()).toBe(1);
  });

  it('提交中重复点确认不会发第二次请求', async () => {
    let release: (v: unknown) => void = () => {};
    mocks.previewSave.mockResolvedValue(previewOk());
    mocks.commitSave.mockImplementation(
      () => new Promise((resolve) => (release = resolve)),
    );

    await saveStore.preview();
    const first = saveStore.confirm(false);
    await saveStore.confirm(false);
    expect(mocks.commitSave).toHaveBeenCalledTimes(1);

    release({ fingerprint: FP, backupPath: 'x.bak' });
    await first;
  });
});
