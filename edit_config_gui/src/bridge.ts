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
  /**
   * 客户端是否以管理员权限运行。
   *
   * 与 `isAdmin` 是两件事：`isAdmin` 说的是「管理器自己」提没提权，`clientAdmin`
   * 说的是「被探测到的客户端进程」有没有提权。客户端提权运行时（`start_client_gui_admin.exe`）
   * 结束它需要管理员权限，普通权限的重启会被拒绝——前端要据此提前提示并走提权路径。
   */
  clientAdmin: boolean;
  /**
   * 服务端进程是否以管理员权限运行。
   *
   * 与 `isAdmin` 同样是两件事：`isAdmin` 说的是「管理器自己」提没提权，`serverAdmin`
   * 说的是「被探测到的服务端进程」有没有提权。服务端提权运行时，普通权限结束不了它，
   * 重启需要提权；探测令牌查询失败时按 `false` 处理。
   */
  serverAdmin: boolean;
}

/** 重启的目标进程。与 Rust `process::ServiceTarget`（`rename_all = "lowercase"`）对应。 */
export type ServiceTarget = 'server' | 'client';

/** 与 Rust `process::RestartOutcome` 对应。 */
export interface RestartOutcome {
  /**
   * 原本以管理员身份运行、但降权启动失败并回退成了普通权限。调用方**必须**把它
   * 显示给用户，不能当成功处理。
   */
  degraded: boolean;
  /**
   * 普通权限无法结束目标进程，需要提权（会弹出 UAC）。为 true 时前端应停在确认框里
   * 改走 `restartServiceElevated`，而不是关闭对话框当作重启完成。
   */
  needsElevation: boolean;
}

/**
 * 与 Rust `system_theme::SystemAppearance` 对应：Windows 当前外观。
 *
 * `accents` 是**候选**种子色而不是一个定值：DWM 色和系统强调色各自都不总是
 * 可信（自动取色时 DWM 色可能接近纯黑），彩度判断放在前端 `lib/theme.ts`。
 */
export interface SystemAppearance {
  dark: boolean;
  accents: string[];
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
   *
   * `needsElevation === true` 表示普通权限结束不了目标进程（例如管理员变体的客户端），
   * 此时并没有完成重启；调用方应改走 `restartServiceElevated`。
   */
  restartService(target: ServiceTarget): Promise<RestartOutcome> {
    return call<RestartOutcome>('restart_service', { target });
  },

  /**
   * 以管理员权限（弹出 UAC）结束并重新拉起服务端/客户端。
   *
   * 只应在 `restartService` 返回 `needsElevation === true` 后调用：它是同一个确认流程的
   * 第二阶段，成功/降权/失败的语义与 `restartService` 一致。
   */
  restartServiceElevated(target: ServiceTarget): Promise<RestartOutcome> {
    return call<RestartOutcome>('restart_service_elevated', { target });
  },

  /**
   * 用系统默认浏览器打开链接（「关于」页的项目主页等）。
   *
   * Rust 侧只放行 `https://`——`file://` 与 `ms-settings:` 之类的协议能拉起本地程序，
   * 而这个命令的入参最终来自渲染进程。
   */
  openUrl(url: string): Promise<void> {
    return call<void>('open_url', { url });
  },

  /**
   * 读系统外观（深浅色 + 主题色候选）。
   *
   * 主题是「用户随时可能在设置里改」的状态，没有变更通知可订阅，所以前端定时轮询
   * 本命令；它只读两个注册表值，成本远低于一次文件 IO。
   */
  systemAppearance(): Promise<SystemAppearance> {
    return call<SystemAppearance>('system_appearance');
  },

  /**
   * 设置页面缩放比例（1 = 100%）。
   *
   * 用 webview 缩放而不是 CSS `zoom`：`vw`/`vh`、媒体查询、固定定位都会跟着重算。
   * Rust 侧只做 0.25–5 的范围兜底，档位由 `lib/stores/zoom.svelte.ts` 决定。
   */
  setZoom(scale: number): Promise<void> {
    return call<void>('set_zoom', { scale });
  },
};
