/**
 * 配置的内存状态：文档基线 + 当前值 + 脏集合 + 校验结果。
 *
 * 三条不变量（都有测试守着，改代码前先看测试）：
 *
 * 1. **补丁类型只看 schema，不看值本身。** `start_music_volume` 在 TOML 里是
 *    字符串 `"100"`，即便控件是滑杆也必须发 `str`；反过来 `mic_seg_duration`
 *    是整数，发成 `str` 会让 Rust 侧 `PatchValue::Str` 写进整数键、下次启动
 *    CapsWriter 读配置时抛转换错误。所以 `buildPatches` 一律用 `FieldMeta.type`
 *    决定 kind，绝不猜。
 * 2. **脏集合自己收缩。** 用户把值改回原样后必须自动从 dirtyIds 里消失，不能靠
 *    「点放弃」。否则「保存」按钮明明没有实质改动却一直可点。
 * 3. **派生只读键永不产生补丁。** 那 9 个 `${model_paths.…}` 占位符是死键，
 *    `util/config.py:249-308` 直接读 `model_paths` 段、根本不解析占位符；
 *    一旦把绝对路径写回这几个键，配置就会分叉成「这台机器是占位符、那台是绝对
 *    路径」，且没有任何代码会读它。
 */

import { bridge } from '../../bridge.ts';
import type { DocState, FieldRule, Patch, PatchValue, Problem } from '../../bridge.ts';
import { allFields, fieldById, fieldId } from '../schema/index.ts';
import type { FieldMeta, JsonValue, ValueType } from '../schema/types.ts';

export type LoadPhase = 'loading' | 'ready' | 'onboarding' | 'error';

/** 动态表的值形状：`{ "<行键>": { "<列>": "<值>" } }` */
type Rows = Record<string, Record<string, string>>;

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

/**
 * 深拷贝一个 JSON 值。
 *
 * 刻意不用 `structuredClone`：vitest 的 jsdom 环境里它是否存在取决于 Node 与
 * jsdom 的版本组合，而配置值全是纯 JSON（TOML 表达不了 NaN/undefined/循环引用），
 * JSON 往返已经足够且哪里都能跑。
 */
function clone<T>(v: T): T {
  return v === undefined ? v : (JSON.parse(JSON.stringify(v)) as T);
}

/** 结构相等。数组与对象按内容比，数字用 `Object.is`（区分 0 / -0、认 NaN）。 */
export function deepEqual(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true;
  if (typeof a !== typeof b) return false;
  if (Array.isArray(a) || Array.isArray(b)) {
    if (!Array.isArray(a) || !Array.isArray(b) || a.length !== b.length) return false;
    return a.every((x, i) => deepEqual(x, b[i]));
  }
  if (isObject(a) && isObject(b)) {
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    return ka.every((k) => deepEqual(a[k], b[k]));
  }
  return false;
}

/** 类型的零值：schema 里没写 `default` 时用它兜底，避免输入框显示 `undefined` */
function zeroOf(type: ValueType): JsonValue {
  switch (type) {
    case 'boolean':
      return false;
    case 'integer':
    case 'float':
      return 0;
    case 'stringArray':
    case 'pairArray':
      return [];
    case 'inlineTable':
      return {};
    default:
      return '';
  }
}

/** 该字段的「默认值」：schema 的 `default`，没有就按类型给零值 */
export function defaultOf(meta: FieldMeta): JsonValue {
  return meta.default !== undefined ? clone(meta.default) : zeroOf(meta.type);
}

/** 整份 schema 的默认值表，`__resetForTest()` 用它当基线 */
function schemaDefaults(): Record<string, JsonValue> {
  const out: Record<string, JsonValue> = {};
  for (const meta of allFields()) out[fieldId(meta.segments)] = defaultOf(meta);
  return out;
}

/**
 * 找出某个叶子所属的动态表描述。
 *
 * 动态表的叶子比描述多两段：描述是 `client.additional_special_apps`，
 * 而文档里的叶子是 `client.additional_special_apps.vlc.exe.name`（行键 `vlc.exe`
 * 里的点属于键本身，不是层级）。所以只能按「长度差 2」反查，不能用 split 猜。
 */
function dynamicMetaOf(segments: string[]): FieldMeta | undefined {
  if (segments.length < 3) return undefined;
  const meta = fieldById(fieldId(segments.slice(0, segments.length - 2)));
  return meta && meta.widget === 'dynamicTable' ? meta : undefined;
}

/**
 * 由文档叶子构造「以 fieldId 为键」的值表。
 *
 * 文档里没有的字段一律补默认值——schema 与某台机器的 config.toml 版本不一致时
 * （用户从旧版升上来，模板里少几个新键），UI 仍然要能正常显示。
 */
export function initialValues(
  fields: { segments: string[]; value: JsonValue }[],
): Record<string, JsonValue> {
  const out: Record<string, JsonValue> = {};

  for (const f of fields) {
    const direct = fieldById(fieldId(f.segments));
    if (direct) {
      out[fieldId(f.segments)] = clone(f.value);
      continue;
    }

    const table = dynamicMetaOf(f.segments);
    if (!table) continue;

    const id = fieldId(table.segments);
    const rows = (out[id] ?? {}) as Rows;
    const rowKey = f.segments[f.segments.length - 2];
    const colKey = f.segments[f.segments.length - 1];
    const row = rows[rowKey] ?? {};
    row[colKey] = String(f.value);
    rows[rowKey] = row;
    out[id] = rows;
  }

  for (const meta of allFields()) {
    const id = fieldId(meta.segments);
    if (!(id in out)) out[id] = defaultOf(meta);
  }
  return out;
}

/** `visibleWhen` 是否成立。未声明的字段恒可见。 */
export function isVisible(
  meta: FieldMeta,
  values: Record<string, JsonValue>,
): boolean {
  const w = meta.visibleWhen;
  if (!w) return true;

  const cur = values[fieldId(w.segments)];
  if (w.in !== undefined) return w.in.some((x) => deepEqual(cur, x));
  if (w.equals !== undefined) return deepEqual(cur, w.equals);

  // 只写了 segments 却没写条件：当作「该键为真值即可见」
  return Boolean(cur);
}

/** 把 UI 上的值按 schema 声明的 TOML 类型包成补丁值 */
export function typedValue(type: ValueType, v: JsonValue): PatchValue {
  switch (type) {
    case 'integer':
      return { kind: 'int', value: Math.trunc(Number(v)) };
    case 'float':
      return { kind: 'float', value: Number(v) };
    case 'boolean':
      return { kind: 'bool', value: Boolean(v) };
    case 'stringArray':
      return { kind: 'strArray', value: (v as string[]).map(String) };
    case 'pairArray':
      return {
        kind: 'pairArray',
        value: (v as JsonValue[]).map((p) => {
          const pair = p as JsonValue[];
          return [String(pair[0]), Number(pair[1])] as [string, number];
        }),
      };
    case 'inlineTable': {
      const row: Record<string, string> = {};
      if (isObject(v)) for (const [k, x] of Object.entries(v)) row[k] = String(x);
      return { kind: 'tableRow', value: row };
    }
    default:
      return { kind: 'str', value: String(v) };
  }
}

/**
 * 比较基线与当前值，产出最小补丁集。
 *
 * 顺序固定为「先逐行写/改，最后删除」：动态表的删除必须排在写入之后，
 * 否则先删一行会让后续 `tableRow` 落到新出现的空位上。
 */
export function buildPatches(
  base: Record<string, JsonValue>,
  cur: Record<string, JsonValue>,
): Patch[] {
  const out: Patch[] = [];

  for (const meta of allFields()) {
    const id = fieldId(meta.segments);
    const before = base[id];
    const after = cur[id];

    // 派生只读键：值来自 model_paths，改它不生效，也绝不写回
    if (meta.widget === 'readonly') continue;
    if (after === undefined) continue;

    if (meta.widget === 'dynamicTable') {
      const rowsBefore = (before ?? {}) as Rows;
      const rowsAfter = (after ?? {}) as Rows;

      for (const [key, row] of Object.entries(rowsAfter)) {
        if (!deepEqual(rowsBefore[key], row)) {
          out.push({
            segments: [...meta.segments, key],
            value: { kind: 'tableRow', value: { ...row } },
          });
        }
      }
      for (const key of Object.keys(rowsBefore)) {
        if (!(key in rowsAfter)) {
          out.push({ segments: [...meta.segments, key], value: { kind: 'delete' } });
        }
      }
      continue;
    }

    if (deepEqual(before, after)) continue;
    out.push({ segments: [...meta.segments], value: typedValue(meta.type, after) });
  }

  return out;
}

/**
 * 当前可见字段的校验规则。
 *
 * 隐藏字段不下发规则：一个被 `visibleWhen` 藏起来的字段（比如关掉 adb 时的
 * `adb_addr`）用户根本看不见，却因为「值不合法」导致保存被拦，属于纯粹的困惑。
 */
export function buildRules(values: Record<string, JsonValue>): FieldRule[] {
  const out: FieldRule[] = [];
  for (const meta of allFields()) {
    if (!meta.validators || meta.validators.length === 0) continue;
    if (!isVisible(meta, values)) continue;
    out.push({
      segments: [...meta.segments],
      validators: [...meta.validators],
      allowEmpty: meta.allowEmpty ?? false,
      fileSuffix: meta.fileSuffix ?? null,
      warnOnly: meta.warnOnly ?? false,
    });
  }
  return out;
}

// ---------------------------------------------------------------- 状态

let phase = $state<LoadPhase>('loading');
let doc = $state.raw<DocState | null>(null);
let values = $state<Record<string, JsonValue>>({});
/** 打开时（或上次提交后）的磁盘值。「放弃全部改动」与脏判定都以它为基准 */
let original = $state.raw<Record<string, JsonValue>>({});
let dirty = $state<Record<string, true>>({});
let errorMap = $state<Record<string, string>>({});
let warnings = $state.raw<Problem[]>([]);
let lastError = $state<string | null>(null);

function describeError(e: unknown): string {
  if (typeof e === 'string') return e;
  if (e instanceof Error) return e.message;
  return String(e);
}

export const configStore = {
  state: (): LoadPhase => phase,

  doc: (): DocState | null => doc,

  values: (): Record<string, JsonValue> => values,

  dirtyIds: (): Set<string> => new Set(Object.keys(dirty)),

  /** DirtyBar 用它决定按钮文案与是否可点（避免每次 `dirtyIds().size` 都在新建 Set） */
  dirtyCount: (): number => Object.keys(dirty).length,

  errors: (): Record<string, string> => errorMap,

  errorOf: (id: string): string | undefined => errorMap[id],

  warnings: (): Problem[] => warnings,

  lastError: (): string | null => lastError,

  /**
   * 提交时要用它做「文件是否被外部改过」的判断。
   *
   * 注意这里读的是变量 `doc` 而不是调用 `configStore.doc()`：`$state`/`$state.raw`
   * 变量在闭包里的读取会被编译器改写成 `$.get(doc)`，再在它后面补一对括号就成了
   * `$.get(doc)()`，运行时报 `get(...) is not a function`，位置还指向这里而不是
   * 定义处，极难看出是这个原因。模块内部的访问器一律直接读变量。
   */
  fingerprint: () => doc?.fingerprint ?? null,

  baseDir: (): string | null => doc?.baseDir ?? null,

  path: (): string | null => doc?.path ?? null,

  setValue(id: string, v: JsonValue): void {
    values[id] = v;

    // 脏集合自己收缩：改回原值就该自动不算脏
    if (deepEqual(v, original[id])) {
      delete dirty[id];
    } else {
      dirty[id] = true;
    }

    // 用户正在改这个字段，上一轮的校验结论已经过期
    if (errorMap[id] !== undefined) delete errorMap[id];
  },

  /**
   * 单字段「恢复默认」。
   *
   * 优先用 schema 的 `default`；没有 `default` 的字段（8 段提示词正文，默认文本
   * 4KB+ 且用户多半改过）退回本次打开时的磁盘值——把提示词强行重置成模板原文
   * 是最容易让人白干一天的操作。
   */
  resetValue(id: string): void {
    const meta = fieldById(id);
    const next = meta?.default !== undefined ? clone(meta.default) : original[id];
    if (next === undefined) return;

    values[id] = next;
    if (deepEqual(next, original[id])) delete dirty[id];
    else dirty[id] = true;
    if (errorMap[id] !== undefined) delete errorMap[id];
  },

  /** 「全部还原」：回磁盘基线，脏集合、错误表、警告一起清 */
  resetAll(): void {
    values = clone(original);
    dirty = {};
    errorMap = {};
    warnings = [];
  },

  patches: (): Patch[] => buildPatches(original, values),

  rules: (): FieldRule[] => buildRules(values),

  async load(path?: string): Promise<void> {
    phase = 'loading';
    lastError = null;
    try {
      configStore.applyDoc(await bridge.openConfig(path));
    } catch (e) {
      lastError = describeError(e);
      // Rust 侧定位失败会返回字面量 NOT_FOUND，用它区分「配置文件不存在，该引导用户」
      // 与「文件存在但读不了/解析不了」
      phase = lastError === 'NOT_FOUND' ? 'onboarding' : 'error';
    }
  },

  async reload(): Promise<void> {
    phase = 'loading';
    lastError = null;
    try {
      configStore.applyDoc(await bridge.reloadConfig());
    } catch (e) {
      lastError = describeError(e);
      phase = 'error';
    }
  },

  applyDoc(d: DocState): void {
    doc = d;
    const base = initialValues(d.fields);
    original = base;
    values = clone(base);
    dirty = {};
    errorMap = {};
    warnings = [];
    lastError = null;
    phase = 'ready';
  },

  /**
   * 落最近一次 `preview_save` 的结论。
   *
   * `errors` / `warnings` 的分流由 Rust 侧按 `FieldRule.warnOnly` 决定，
   * 前端不再二次判断——两处各判一次迟早会不一致，而这里判错的后果是
   * 「模型文件缺失」变成阻断保存。
   */
  applyProblems(p: { errors: Problem[]; warnings: Problem[] }): void {
    const map: Record<string, string> = {};
    for (const e of p.errors) map[fieldId(e.segments)] = e.message;
    errorMap = map;
    warnings = p.warnings;
  },

  /** 提交成功后，把新指纹写回，避免下一次保存误报「文件被外部改过」 */
  setFingerprint(fp: DocState['fingerprint']): void {
    if (doc) doc = { ...doc, fingerprint: fp };
  },

  /**
   * 提交成功后重设基线。
   *
   * 三件事必须一起做，少一件都会留下不一致：
   * 1. `original` 换成当前值 —— 否则 `patches()` 仍按旧基线算，用户会看到
   *    「已保存」但脏标记和保存按钮还不消失；
   * 2. 清 `dirty` / `errorMap` / `warnings` —— 这些都是「相对旧基线」的结论；
   * 3. 记下新指纹 —— 否则下一次保存必报 `CONFLICT`（磁盘的 mtime 已变）。
   *
   * 这里刻意不重新读盘：`commit_save` 已经把写进去的内容原子替换并回读校验过，
   * 再读一次只会引入「读的那一刻又被别人改了」的新窗口。
   */
  commitSucceeded(fp: DocState['fingerprint']): void {
    original = clone(values);
    dirty = {};
    errorMap = {};
    warnings = [];
    if (doc) doc = { ...doc, fingerprint: fp };
  },

  __resetForTest(): void {
    const base = schemaDefaults();
    original = base;
    values = clone(base);
    dirty = {};
    errorMap = {};
    warnings = [];
    lastError = null;
    doc = null;
    phase = 'ready';
  },

  setError(id: string, message: string): void {
    errorMap[id] = message;
  },
};
