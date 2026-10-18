import type { FieldMeta, PageMeta } from './types';
import { serverPages } from './server';

export * from './types';

/**
 * 13 页的权威顺序。`navStore.focus()` 反查页 id、侧边栏顺序、
 * `PageView` 对 `about` 页的特判都以这里为准（见计划里「页 id 与标题的权威表」）。
 */
export const pages: PageMeta[] = [...serverPages];

/**
 * 字段的唯一键：segments 用 U+0000 连接。
 *
 * 不能用 `.` 连接 —— `client.additional_special_apps` 的键字面就是 `vlc.exe`，
 * 点分形式会和真正的层级混淆，解不出唯一路径。
 */
export const fieldId = (segments: string[]): string => segments.join('\u0000');

export function allFields(): FieldMeta[] {
  return pages.flatMap((p) => p.sections.flatMap((s) => s.fields));
}

export function fieldById(id: string): FieldMeta | undefined {
  return allFields().find((f) => fieldId(f.segments) === id);
}

/** 9 个派生只读键：`derivedFrom` 指向真实生效的 model_paths 键 */
export function derivedFields(): FieldMeta[] {
  return allFields().filter((f) => f.derivedFrom !== undefined);
}
