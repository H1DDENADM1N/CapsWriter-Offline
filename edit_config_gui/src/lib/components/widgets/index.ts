import type { Component } from 'svelte';
import type { WidgetKind } from '../../schema/types.ts';
import type { WidgetProps } from './props.ts';

import BoolWidget from './BoolWidget.svelte';
import DynamicTableWidget from './DynamicTableWidget.svelte';
import EnumWidget from './EnumWidget.svelte';
import FloatWidget from './FloatWidget.svelte';
import HotkeyWidget from './HotkeyWidget.svelte';
import IntWidget from './IntWidget.svelte';
import LongTextWidget from './LongTextWidget.svelte';
import PairListWidget from './PairListWidget.svelte';
import PathWidget from './PathWidget.svelte';
import ReadonlyWidget from './ReadonlyWidget.svelte';
import SecretWidget from './SecretWidget.svelte';
import StringListWidget from './StringListWidget.svelte';
import TextWidget from './TextWidget.svelte';

export type { WidgetProps } from './props.ts';

/**
 * 控件种类 → 组件。
 *
 * 用 `Record<WidgetKind, …>` 而不是普通对象：schema 里新增一种 widget 却忘了
 * 在这里接线时，`pnpm check` 直接报缺少属性，比运行时渲染成空白好得多。
 */
const REGISTRY: Record<WidgetKind, Component<WidgetProps>> = {
  text: TextWidget,
  secret: SecretWidget,
  longText: LongTextWidget,
  bool: BoolWidget,
  enum: EnumWidget,
  int: IntWidget,
  float: FloatWidget,
  hotkey: HotkeyWidget,
  path: PathWidget,
  stringList: StringListWidget,
  pairList: PairListWidget,
  dynamicTable: DynamicTableWidget,
  readonly: ReadonlyWidget,
};

export function widgetFor(kind: WidgetKind): Component<WidgetProps> {
  return REGISTRY[kind];
}
