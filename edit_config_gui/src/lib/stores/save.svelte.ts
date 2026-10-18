/**
 * 保存流程的状态机。
 *
 * 抽成 store 而不是塞进 `DiffDialog` 的原因：一次保存要跨「预览 → 确认 → 提交 →
 * 冲突/成功」四个阶段，其中冲突阶段还要给用户两个分叉（重载 / 强制覆盖）。
 * 这些阶段是流程状态，不是某个对话框的临时 UI 状态；放进组件里会导致
 * 「对话框关掉后流程状态丢失」，重开保存又从头跑一遍 diff。
 *
 * 一句容易写错的约定：Tauri 2 命令返回 `Result<T, String>` 时，`invoke` 被 reject
 * 的**就是那个字符串本身**（不是 `Error`）。所以冲突判定必须写
 * `String(e) === 'CONFLICT'`；写成 `(e as Error).message === 'CONFLICT'` 恒为
 * `undefined`，冲突永远识别不到，用户点保存只会看到一句莫名失败。
 */

import { bridge } from '../../bridge.ts';
import type { PreviewResult } from '../../bridge.ts';
import type { JsonValue } from '../schema/types.ts';
import { configStore } from './config.svelte.ts';

export type SavePhase =
  | { kind: 'idle' }
  | { kind: 'previewing' }
  | { kind: 'confirm'; result: PreviewResult }
  | { kind: 'committing' }
  | { kind: 'conflict'; error: string }
  | { kind: 'done'; backupPath: string }
  | { kind: 'failed'; error: string };

let phase = $state<SavePhase>({ kind: 'idle' });

function describe(e: unknown): string {
  if (typeof e === 'string') return e;
  if (e instanceof Error) return e.message;
  return String(e);
}

function isConflict(e: unknown): boolean {
  return describe(e) === 'CONFLICT';
}

export const saveStore = {
  phase: (): SavePhase => phase,

  /** 正在等后端或正在写盘：此时不允许再发一次 */
  busy: (): boolean => phase.kind === 'previewing' || phase.kind === 'committing',

  /**
   * 调 `preview_save`：只算 diff 与校验结果，不写盘。
   *
   * 有 error 时**不进 confirm 态**——先把错误标到各自字段上，让用户去改；
   * 弹一个「有 N 个错误」的对话框再让他关掉，等于多一次无效点击。
   */
  async preview(): Promise<void> {
    if (saveStore.busy()) return;

    const patches = configStore.patches();
    if (patches.length === 0) return;

    phase = { kind: 'previewing' };
    try {
      const result = await bridge.previewSave(patches, configStore.rules());
      configStore.applyProblems({ errors: result.errors, warnings: result.warnings });

      if (result.errors.length > 0) {
        phase = { kind: 'idle' };
        return;
      }
      phase = { kind: 'confirm', result };
    } catch (e) {
      phase = { kind: 'failed', error: describe(e) };
    }
  },

  /**
   * 用户点了确认。
   *
   * `force` 只在冲突分支的「强制覆盖」里为 true：那时磁盘上的文件已经被别人
   * （config_selector、其它编辑器、上一次会话）改过，用户明确表示「我这份内存
   * 里的改动要盖掉它」。
   *
   * 失败一律只写一次盘、不自动重试：`ReplaceFileW` 的失败原因可能是权限、占用、
   * 磁盘满，自动重试只会把「一次写失败」放大成「三秒内三次写失败」。
   */
  async confirm(force: boolean): Promise<void> {
    if (saveStore.busy()) return;

    const patches = configStore.patches();
    if (patches.length === 0) {
      phase = { kind: 'idle' };
      return;
    }

    const fingerprint = configStore.fingerprint();
    if (fingerprint === null) {
      phase = { kind: 'failed', error: '还没有打开过配置文件，无法保存' };
      return;
    }

    phase = { kind: 'committing' };
    try {
      const result = await bridge.commitSave(patches, configStore.rules(), fingerprint, force);
      configStore.commitSucceeded(result.fingerprint);
      phase = { kind: 'done', backupPath: result.backupPath };
    } catch (e) {
      if (isConflict(e)) {
        phase = { kind: 'conflict', error: '配置文件已被外部修改' };
        return;
      }
      phase = { kind: 'failed', error: describe(e) };
    }
  },

  /** 关闭对话框：只清流程状态，不动配置值（用户可能还想继续改） */
  cancel(): void {
    phase = { kind: 'idle' };
  },

  /** 冲突分支的「重新加载」：丢弃内存改动，按磁盘现状重读 */
  async reloadAndReset(): Promise<void> {
    phase = { kind: 'idle' };
    await configStore.reload();
  },

  /** 「放弃全部改动」：回磁盘基线，不碰文件 */
  discardAll(): void {
    configStore.resetAll();
  },
};

// 供测试读取当前 patch 数量时少写一行（DirtyBar 用 configStore.patches() 即可）
export type SaveState = { phase: SavePhase };

export type { JsonValue };
