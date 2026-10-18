import type { FieldMeta, JsonValue } from '../../schema/types.ts';

/**
 * 所有控件共用的 props 形状。
 *
 * `value` 允许 `undefined`：动态表里新加的一行、或者配置里本来就缺的键
 * （`core_client.py` 里有若干带默认值的 `config.get(...)`），都会走到这里。
 * 控件不得假设它一定是某个具体类型。
 *
 * 控件只负责「把用户操作翻译成一个新值」并通过 `onChange` 上报，**不写 store、
 * 不拼补丁、不做跨字段联动**——补丁类型由 `config.svelte.ts` 的 `typedValue`
 * 按 `field.type` 决定（`start_music_volume` 在 TOML 里是字符串 "100"，
 * 控件是滑杆也必须上报字符串），校验由 Rust 侧的 `validate.rs` 兜底。
 */
export interface WidgetProps {
  field: FieldMeta;
  value: JsonValue | undefined;
  /** 该字段当前的错误文案；控件只用它决定边框颜色，不显示文字 */
  error?: string;
  onChange: (v: JsonValue) => void;
}
