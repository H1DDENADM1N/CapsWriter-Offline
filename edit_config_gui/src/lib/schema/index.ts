import type { FieldMeta, PageMeta } from './types.ts';
import { serverPages } from './server.ts';
import { clientPage } from './client.ts';
import { aiProvidersPage } from './aiProviders.ts';
import { promptStylesPage } from './promptStyles.ts';
import { additionalAppsPage } from './additionalApps.ts';
import { libretranslatePage, deeplxPage } from './translate.ts';
import { modelPathsPage } from './modelPaths.ts';
import { funasrPage, sensevoicePage, paraformerPage, qwenCtcPage } from './modelArgs.ts';

export * from './types.ts';

/**
 * 14 页的权威顺序。`navStore.focus()` 反查页 id、侧边栏顺序、`PageView` 对
 * `about` 页的特判都以这里为准（见计划里「页 id 与标题的权威表」）。
 *
 * 第 14 页「关于」不在 schema 里 —— 它没有任何配置键，`sections` 为空，由
 * `PageView` 特判渲染（版本、config.toml 绝对路径、项目地址、迁移说明）。
 */
export const pages: PageMeta[] = [
  serverPages[0],
  clientPage,
  aiProvidersPage,
  promptStylesPage,
  additionalAppsPage,
  libretranslatePage,
  deeplxPage,
  modelPathsPage,
  funasrPage,
  sensevoicePage,
  paraformerPage,
  qwenCtcPage,
  serverPages[1],
  {
    id: 'about',
    title: '关于',
    icon: 'info',
    sections: [],
  },
];

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

/** 13 个派生只读键：`derivedFrom` 指向真实生效的 model_paths 键 */
export function derivedFields(): FieldMeta[] {
  return allFields().filter((f) => f.derivedFrom !== undefined);
}

/**
 * 可编辑的固定叶子键 = 全部字段 减去动态表描述、减去派生只读键。
 *
 * `schema_paths.json` 断言的就是这一组（163 条）：178 个 TOML 叶子
 * − 2 条动态表条目 − 13 个派生只读键 = 163。
 */
export function editableFields(): FieldMeta[] {
  return allFields().filter(
    (f) => f.widget !== 'dynamicTable' && f.widget !== 'readonly',
  );
}

/** 反查某个 segments 属于哪一页（`navStore.focus()` 用，不能靠 segments[0] 猜） */
export function pageOfSegments(segments: string[]): PageMeta | undefined {
  return pages.find((p) =>
    p.sections.some((s) =>
      s.fields.some(
        (f) =>
          // 前缀匹配而非等长：动态表的行是 4 段（`…additional_special_apps.vlc.exe`），
          // 而表本身只登记了 2 段；等长比较会让「跳到某个进程名」找不到页。
          f.segments.length <= segments.length &&
          f.segments.every((x, i) => x === segments[i]),
      ),
    ),
  );
}

/** 反查某个 segments 所属的页 + 小节（面包屑与搜索结果用） */
export function locate(
  segments: string[],
): { page: PageMeta; section: PageMeta['sections'][number] } | undefined {
  for (const page of pages) {
    for (const section of page.sections) {
      const hit = section.fields.some(
        (f) =>
          f.segments.length === segments.length &&
          f.segments.every((x, i) => x === segments[i]),
      );
      if (hit) return { page, section };
    }
  }
  return undefined;
}
