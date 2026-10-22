/**
 * 字段元数据：14 个页面 × 188 个键的唯一描述来源。
 *
 * 设计约束（规格 §5.1 / §5.2）：
 * - **定位一律用 `segments`**，`path` 只是给人看和给搜索用的点分展示串。
 *   `client.additional_special_apps` 的键是 `vlc.exe`（含点）、
 *   `client.多音字` 是非 ASCII，任何「按点 split」的写法都会出错。
 * - 与规格 §5.1 的差异只有两处，均为实现必需：
 *   ① `path` 降级为展示字段、`segments` 承担唯一定位职责；
 *   ② 新增 `warnOnly`，让「`model_paths.*` 校验失败只警告不阻断」能声明式表达
 *      （规格 §9.3 / §6.4），不必在 Rust 里硬编码路径前缀。
 */

export type JsonValue =
  | string
  | number
  | boolean
  | JsonValue[]
  | { [k: string]: JsonValue };

/** 对应 config.toml 里值的 TOML 类型（Rust 侧 `TomlType` 的镜像） */
export type ValueType =
  | 'string'
  | 'integer'
  | 'float'
  | 'boolean'
  | 'stringArray'
  | 'pairArray'
  | 'inlineTable';

export type ValidatorId =
  | 'ip'
  | 'localListenableIp'
  | 'port'
  | 'fileExist'
  | 'dirExist'
  | 'hotkey'
  | 'url'
  | 'singleLine'
  | 'ipPort'
  | 'regexClass';

export type WidgetKind =
  | 'text'
  | 'int'
  | 'float'
  | 'bool'
  | 'enum'
  | 'path'
  | 'hotkey'
  | 'stringList'
  | 'pairList'
  | 'longText'
  | 'secret'
  | 'readonly'
  | 'dynamicTable';

export interface FieldMeta {
  /** 点分路径，**仅**用于展示与搜索；定位一律用 segments */
  path: string;
  segments: string[];
  title: string;
  /** 来自 config.toml 里该键下方的注释原文（多行用 \n 连） */
  note?: string;
  type: ValueType;
  widget: WidgetKind;
  default?: JsonValue;
  options?: { value: string; label: string }[];
  min?: number;
  max?: number;
  step?: number;
  validators?: ValidatorId[];
  /** 空串是合法值（如「留空则不暂停」的暂停快捷键） */
  allowEmpty?: boolean;
  pathMode?: 'file' | 'directory';
  fileSuffix?: string;
  visibleWhen?: { segments: string[]; equals?: JsonValue; in?: JsonValue[] };
  /** 只读派生：真实生效位置的 segments */
  derivedFrom?: string[];
  /** 搜索同义词（规格 §9.7.2） */
  aliases?: string[];
  /** 该字段校验失败只警告、不阻断保存（`model_paths.*`） */
  warnOnly?: boolean;
}

export interface SectionMeta {
  id: string;
  title: string;
  note?: string;
  fields: FieldMeta[];
}

export interface PageMeta {
  id: string;
  title: string;
  /** 侧边栏图标名（SVG 内联，见 Task 20） */
  icon: string;
  sections: SectionMeta[];
}
