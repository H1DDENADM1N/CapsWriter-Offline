/**
 * 前端与 Rust 之间唯一的 IPC 出口。
 *
 * 三条纪律：
 * 1. **只有这个文件可以 `import { invoke }`**。散落在组件里的 `invoke("preview_save", …)`
 *    拼错命令名 Tauri 只会在运行时抛 "command not found"，而 TypeScript 完全看不见；
 *    收在一处后，命令名与参数形状都只在这里出现一次。
 * 2. 类型与 Rust 侧 `#[serde(rename_all = "camelCase")]` 逐字对应。字段名对不上时
 *    serde 会在**反序列化入参**时失败，错误信息形如 `invalid type: null`，极难定位，
 *    所以这里的形状改动必须同步改 `src-tauri/src/commands.rs` 的 derive。
 * 3. `PatchValue` 的 `kind` 字符串由 Rust 枚举变体名经 camelCase 得到
 *    （`Str`→`str`、`TableRow`→`tableRow`、`Delete`→`delete`，后者没有 `value`）。
 */

import { invoke } from '@tauri-apps/api/core';

import type { JsonValue, ValidatorId } from './lib/schema/types.ts';

/** 与 Rust `file_io::FileFingerprint` 对应。`mtimeMs` 是毫秒时间戳（可能是负数）。 */
export interface FileFingerprint {
  mtimeMs: number;
  size: number;
  sha256: string;
}

/** 与 Rust `commands::FieldView` 对应：文档里一个叶子的当前值。 */
export interface FieldView {
  segments: string[];
  value: JsonValue;
  /** `config_doc::toml_type_name` 的返回值：string / integer / float / boolean / array / inlineTable */
  tomlType: string;
}

export interface DocState {
  path: string;
  fingerprint: FileFingerprint;
  fields: FieldView[];
  /** config.toml 所在目录，前端拼相对路径时用（不参与写回） */
  baseDir: string;
}

export type PatchValue =
  | { kind: 'str'; value: string }
  | { kind: 'int'; value: number }
  | { kind: 'float'; value: number }
  | { kind: 'bool'; value: boolean }
  | { kind: 'strArray'; value: string[] }
  /** TOML 里是 `[["进程名", 延迟], …]`，非空二元组 */
  | { kind: 'pairArray'; value: [string, number][] }
  /** 动态表的一个条目；值是该条目的全部列（不是增量，漏列会被当删除） */
  | { kind: 'tableRow'; value: Record<string, string> }
  /** 删除一个键、一个数组的首元素，或一个动态表条目 */
  | { kind: 'delete' };

export interface Patch {
  segments: string[];
  value: PatchValue;
}

/** 与 Rust `validate::FieldRule` 对应。`fileSuffix` 在 Rust 侧是 `Option<String>`，故可为 null。 */
export interface FieldRule {
  segments: string[];
  validators: ValidatorId[];
  allowEmpty: boolean;
  fileSuffix: string | null;
  warnOnly: boolean;
}

export interface Problem {
  segments: string[];
  message: string;
}

export interface PreviewResult {
  diff: string;
  errors: Problem[];
  warnings: Problem[];
  changed: string[][];
}

export interface CommitResult {
  fingerprint: FileFingerprint;
  /** 提交后生成的备份绝对路径（同目录 `config.toml.bak`） */
  backupPath: string;
}

export interface RunningInfo {
  server: boolean;
  client: boolean;
  /** 只有客户端在跑时才有值，例如 `start_client_gui_admin.exe` */
  clientVariant: string | null;
  isAdmin: boolean;
}

/**
 * 不在 Tauri 窗口里就立刻给出可读的错误。
 *
 * 否则 `invoke` 会在 `window.__TAURI_INTERNALS__` 上抛 `Cannot read properties of
 * undefined`，看起来像代码 bug 而不是「用错了运行方式」——浏览器里 `pnpm dev`
 * 预览 UI 时最容易踩。
 */
function ensureTauri(): void {
  if (typeof window === 'undefined' || !('__TAURI_INTERNALS__' in window)) {
    throw new Error('当前不在 Tauri 窗口中运行，无法读写配置（请用 pnpm dev:tauri）');
  }
}

async function call<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  ensureTauri();
  return invoke<T>(cmd, args);
}

export const bridge = {
  /** 不传 path 时由 Rust 按「exe 同目录 → cwd」定位 config.toml */
  openConfig(path?: string): Promise<DocState> {
    return call<DocState>('open_config', { path: path ?? null });
  },

  /** 系统文件/文件夹选择框。用户取消时返回 null（不是抛错）。 */
  pickPath(mode: 'file' | 'dir', title: string): Promise<string | null> {
    return call<string | null>('pick_path', { mode, title });
  },

  /** 只算 diff 与校验结果，绝不写盘 */
  previewSave(patches: Patch[], rules: FieldRule[]): Promise<PreviewResult> {
    return call<PreviewResult>('preview_save', { patches, rules });
  },

  /**
   * @param fingerprint 打开（或上次提交）时的指纹，用于发现「文件被别人改过」
   * @param force 用户已在冲突提示里确认「覆盖外部改动」时传 true
   */
  commitSave(
    patches: Patch[],
    rules: FieldRule[],
    fingerprint: FileFingerprint,
    force: boolean,
  ): Promise<CommitResult> {
    return call<CommitResult>('commit_save', { patches, rules, fingerprint, force });
  },

  /** 丢弃内存改动、按磁盘现状重读 */
  reloadConfig(): Promise<DocState> {
    return call<DocState>('reload_config');
  },

  runningProcesses(): Promise<RunningInfo> {
    return call<RunningInfo>('running_processes');
  },

  /**
   * 结束并以正确变体重新拉起服务端/客户端。
   *
   * `degraded === true` 表示原本以管理员身份运行、但降权启动失败并回退成了普通权限——
   * 调用方**必须**把它显示给用户，不能当成功处理。
   */
  restartService(target: 'server' | 'client'): Promise<{ degraded: boolean }> {
    return call<{ degraded: boolean }>('restart_service', { target });
  },
};
