import type { IconifyIcon } from '@iconify/types';
import type { FieldMeta, WidgetKind } from './schema/types.ts';

/*
 * 每一行配置项前面的 MD3 图标。
 *
 * 图标来自 Google Material Symbols（`@ktibow/iconset-material-symbols` 是它的
 * Iconify 数据包，每个图标一个模块）。这里**只显式导入用到的那些**，不要
 * `import * as icons`：整包 15800+ 个图标，一旦被当作命名空间导入就没法摇树，
 * 打出来的包会多出几十兆。
 *
 * 映射的键是 `FieldMeta.path`（点分展示串）。之所以不写进 schema 的每个字段对象：
 * schema 里大量字段由 `dirField()` / `fileField()` / `mkField()` 这类工厂批量生成，
 * 逐条塞图标会让工厂签名变得又长又吵；集中成一张表反而一眼能看出「每个配置项
 * 各自是什么图形」，加字段时也只改一个地方。`fieldIcons.test.ts` 会保证表与
 * `allFields()` 双向对齐（缺项、多出来的陈旧键都会报错）。
 */

// —— 服务端/客户端连接 ——
import lan from '@ktibow/iconset-material-symbols/lan.js';
import settingsEthernet from '@ktibow/iconset-material-symbols/settings-ethernet.js';
import link from '@ktibow/iconset-material-symbols/link.js';
import terminal from '@ktibow/iconset-material-symbols/terminal.js';
import code from '@ktibow/iconset-material-symbols/code.js';
import sync from '@ktibow/iconset-material-symbols/sync.js';
import wifiTethering from '@ktibow/iconset-material-symbols/wifi-tethering.js';
import smartphone from '@ktibow/iconset-material-symbols/smartphone.js';

// —— 进程/窗口/启动 ——
import dock from '@ktibow/iconset-material-symbols/dock.js';
import filter1 from '@ktibow/iconset-material-symbols/filter-1.js';
import rocketLaunch from '@ktibow/iconset-material-symbols/rocket-launch.js';
import adminPanelSettings from '@ktibow/iconset-material-symbols/admin-panel-settings.js';
import touchApp from '@ktibow/iconset-material-symbols/touch-app.js';
import block from '@ktibow/iconset-material-symbols/block.js';
import keyboardReturn from '@ktibow/iconset-material-symbols/keyboard-return.js';

// —— 录音/麦克风/音频 ——
import mic from '@ktibow/iconset-material-symbols/mic.js';
import keyboardVoice from '@ktibow/iconset-material-symbols/keyboard-voice.js';
import timer from '@ktibow/iconset-material-symbols/timer.js';
import layers from '@ktibow/iconset-material-symbols/layers.js';
import settingsBackupRestore from '@ktibow/iconset-material-symbols/settings-backup-restore.js';
import speed from '@ktibow/iconset-material-symbols/speed.js';
import contentCut from '@ktibow/iconset-material-symbols/content-cut.js';
import contentPaste from '@ktibow/iconset-material-symbols/content-paste.js';
import playCircle from '@ktibow/iconset-material-symbols/play-circle.js';
import stopCircle from '@ktibow/iconset-material-symbols/stop-circle.js';
import pauseCircle from '@ktibow/iconset-material-symbols/pause-circle.js';
import audioFile from '@ktibow/iconset-material-symbols/audio-file.js';
import volumeUp from '@ktibow/iconset-material-symbols/volume-up.js';
import volumeDown from '@ktibow/iconset-material-symbols/volume-down.js';
import volumeMute from '@ktibow/iconset-material-symbols/volume-mute.js';
import musicNote from '@ktibow/iconset-material-symbols/music-note.js';
import libraryMusic from '@ktibow/iconset-material-symbols/library-music.js';
import liveTv from '@ktibow/iconset-material-symbols/live-tv.js';
import headphones from '@ktibow/iconset-material-symbols/headphones.js';
import hearing from '@ktibow/iconset-material-symbols/hearing.js';
import mouse from '@ktibow/iconset-material-symbols/mouse.js';
import autoAwesome from '@ktibow/iconset-material-symbols/auto-awesome.js';

// —— 热词/规则/文本处理 ——
import tag from '@ktibow/iconset-material-symbols/tag.js';
import label from '@ktibow/iconset-material-symbols/label.js';
import dictionary from '@ktibow/iconset-material-symbols/dictionary.js';
import equalizer from '@ktibow/iconset-material-symbols/equalizer.js';
import rule from '@ktibow/iconset-material-symbols/rule.js';
import bookmark from '@ktibow/iconset-material-symbols/bookmark.js';
import numbers from '@ktibow/iconset-material-symbols/numbers.js';
import percent from '@ktibow/iconset-material-symbols/percent.js';
import formatQuote from '@ktibow/iconset-material-symbols/format-quote.js';
import spaceBar from '@ktibow/iconset-material-symbols/space-bar.js';
import textFields from '@ktibow/iconset-material-symbols/text-fields.js';
import subject from '@ktibow/iconset-material-symbols/subject.js';
import description from '@ktibow/iconset-material-symbols/description.js';
import notes from '@ktibow/iconset-material-symbols/notes.js';
import dataObject from '@ktibow/iconset-material-symbols/data-object.js';
import subtitles from '@ktibow/iconset-material-symbols/subtitles.js';
import merge from '@ktibow/iconset-material-symbols/merge.js';
import formatSize from '@ktibow/iconset-material-symbols/format-size.js';
import compress from '@ktibow/iconset-material-symbols/compress.js';
import save from '@ktibow/iconset-material-symbols/save.js';

// —— 翻译 ——
import translate from '@ktibow/iconset-material-symbols/translate.js';
import gTranslate from '@ktibow/iconset-material-symbols/g-translate.js';
import language from '@ktibow/iconset-material-symbols/language.js';
import cloud from '@ktibow/iconset-material-symbols/cloud.js';
import cloudOff from '@ktibow/iconset-material-symbols/cloud-off.js';

// —— AI ——
import smartToy from '@ktibow/iconset-material-symbols/smart-toy.js';
import psychology from '@ktibow/iconset-material-symbols/psychology.js';
import vpnKey from '@ktibow/iconset-material-symbols/vpn-key.js';
import style from '@ktibow/iconset-material-symbols/style.js';
import notifications from '@ktibow/iconset-material-symbols/notifications.js';
import schedule from '@ktibow/iconset-material-symbols/schedule.js';
import favorite from '@ktibow/iconset-material-symbols/favorite.js';
import share from '@ktibow/iconset-material-symbols/share.js';
import brush from '@ktibow/iconset-material-symbols/brush.js';
import school from '@ktibow/iconset-material-symbols/school.js';
import supportAgent from '@ktibow/iconset-material-symbols/support-agent.js';
import editNote from '@ktibow/iconset-material-symbols/edit-note.js';
import apps from '@ktibow/iconset-material-symbols/apps.js';

// —— 模型路径/推理参数 ——
import folder from '@ktibow/iconset-material-symbols/folder.js';
import folderOpen from '@ktibow/iconset-material-symbols/folder-open.js';
import filePresent from '@ktibow/iconset-material-symbols/file-present.js';
import modelTraining from '@ktibow/iconset-material-symbols/model-training.js';
import bolt from '@ktibow/iconset-material-symbols/bolt.js';
import memory from '@ktibow/iconset-material-symbols/memory.js';
import developerBoard from '@ktibow/iconset-material-symbols/developer-board.js';
import precisionManufacturing from '@ktibow/iconset-material-symbols/precision-manufacturing.js';
import graphicEq from '@ktibow/iconset-material-symbols/graphic-eq.js';
import straighten from '@ktibow/iconset-material-symbols/straighten.js';
import tune from '@ktibow/iconset-material-symbols/tune.js';
import computer from '@ktibow/iconset-material-symbols/computer.js';
import checklist from '@ktibow/iconset-material-symbols/checklist.js';
import bugReport from '@ktibow/iconset-material-symbols/bug-report.js';

// —— 兜底（控件类型默认图标） ——
import toggleOn from '@ktibow/iconset-material-symbols/toggle-on.js';
import list from '@ktibow/iconset-material-symbols/list.js';
import formatListBulleted from '@ktibow/iconset-material-symbols/format-list-bulleted.js';
import tableChart from '@ktibow/iconset-material-symbols/table-chart.js';
import keyboard from '@ktibow/iconset-material-symbols/keyboard.js';
import factCheck from '@ktibow/iconset-material-symbols/fact-check.js';
import info from '@ktibow/iconset-material-symbols/info.js';

/**
 * 图标登记表：只把「映射里真的用到」的名字放进来。
 * `fieldIcons.test.ts` 会检查映射里的每个值都在这里，写错名字当场变红。
 */
export const ICONS: Record<string, IconifyIcon> = {
  lan,
  'settings-ethernet': settingsEthernet,
  link,
  terminal,
  code,
  sync,
  'wifi-tethering': wifiTethering,
  smartphone,
  dock,
  'filter-1': filter1,
  'rocket-launch': rocketLaunch,
  'admin-panel-settings': adminPanelSettings,
  'touch-app': touchApp,
  block,
  'keyboard-return': keyboardReturn,
  mic,
  'keyboard-voice': keyboardVoice,
  timer,
  layers,
  'settings-backup-restore': settingsBackupRestore,
  speed,
  'content-cut': contentCut,
  'content-paste': contentPaste,
  'play-circle': playCircle,
  'stop-circle': stopCircle,
  'pause-circle': pauseCircle,
  'audio-file': audioFile,
  'volume-up': volumeUp,
  'volume-down': volumeDown,
  'volume-mute': volumeMute,
  'music-note': musicNote,
  'library-music': libraryMusic,
  'live-tv': liveTv,
  headphones,
  hearing,
  mouse,
  'auto-awesome': autoAwesome,
  tag,
  label,
  dictionary,
  equalizer,
  rule,
  bookmark,
  numbers,
  percent,
  'format-quote': formatQuote,
  'space-bar': spaceBar,
  'text-fields': textFields,
  subject,
  description,
  notes,
  'data-object': dataObject,
  subtitles,
  merge,
  'format-size': formatSize,
  compress,
  save,
  translate,
  'g-translate': gTranslate,
  language,
  cloud,
  'cloud-off': cloudOff,
  'smart-toy': smartToy,
  psychology,
  'vpn-key': vpnKey,
  style,
  notifications,
  schedule,
  favorite,
  share,
  brush,
  school,
  'support-agent': supportAgent,
  'edit-note': editNote,
  apps,
  folder,
  'folder-open': folderOpen,
  'file-present': filePresent,
  'model-training': modelTraining,
  bolt,
  memory,
  'developer-board': developerBoard,
  'precision-manufacturing': precisionManufacturing,
  'graphic-eq': graphicEq,
  straighten,
  tune,
  computer,
  checklist,
  'bug-report': bugReport,
  'toggle-on': toggleOn,
  list,
  'format-list-bulleted': formatListBulleted,
  'table-chart': tableChart,
  keyboard,
  info,
  'fact-check': factCheck,
};

/**
 * 按 `FieldMeta.path` 逐项指定。
 *
 * 选图标的几条自制规则，方便以后加字段时保持一致：
 * - 「同一个概念」用同一个图标：所有端口都用 `settings-ethernet`，所有 hotkey
 *   都用 `keyboard` 系，所有模型文件都用 `file-present`，所有目录都用 `folder`。
 * - 一个字段只有一个图标，不为了凑数换图形；重复的图标反而更好读。
 * - 顶层开关用「它开启/关闭的那件事」的图标，不要一律用开关图形。
 */
export const FIELD_ICONS: Record<string, string> = {
  // ── 服务端 ──
  'server.model': 'model-training',
  'server.expand_funasr_hotwords': 'auto-awesome',
  'server.addr': 'lan',
  'server.speech_recognition_port': 'settings-ethernet',
  'server.check_port_usage_before_start': 'fact-check',
  'server.start_online_translate_server': 'cloud',
  'server.start_offline_translate_server': 'cloud-off',
  'server.offline_translate_port': 'settings-ethernet',
  'server.format_num': 'numbers',
  'server.format_punc': 'format-quote',
  'server.format_spell': 'space-bar',
  'server.shrink_automatically_to_tray': 'dock',
  'server.only_run_once': 'filter-1',
  'server.in_the_meantime_start_the_client': 'rocket-launch',
  'server.in_the_meantime_start_the_client_and_run_as_admin': 'admin-panel-settings',

  // ── 客户端：通用 ──
  'client.addr': 'lan',
  'client.shrink_automatically_to_tray': 'dock',
  'client.only_run_once': 'filter-1',
  'client.vscode_exe_path': 'code',
  'client.disable_exe_list_on_focus': 'touch-app',
  'client.disable_exe_list': 'block',
  'client.enter_apps': 'keyboard-return',
  'client.enable_adb_control': 'smartphone',
  'client.adb_addr': 'wifi-tethering',

  // ── 客户端：语音识别 ──
  'client.speech_recognition_shortcut': 'keyboard-voice',
  'client.only_enable_microphones_when_pressed_record_shortcut': 'mic',
  'client.speech_recognition_port': 'settings-ethernet',
  'client.mic_seg_duration': 'timer',
  'client.mic_seg_overlap': 'layers',
  'client.hold_mode': 'touch-app',
  'client.suppress': 'block',
  'client.restore_key': 'settings-backup-restore',
  'client.threshold': 'speed',
  'client.trash_punc': 'content-cut',
  'client.paste': 'content-paste',
  'client.restore_clipboard_after_paste': 'settings-backup-restore',
  'client.play_start_music': 'play-circle',
  'client.start_music_path': 'audio-file',
  'client.start_music_volume': 'volume-up',
  'client.play_stop_music': 'stop-circle',
  'client.stop_music_path': 'audio-file',
  'client.stop_music_volume': 'volume-down',
  'client.mute_other_audio': 'volume-mute',
  'client.pause_other_audio': 'pause-circle',
  'client.QQMusic_global_pause_hotkey': 'music-note',
  'client.CloudMusic_global_pause_hotkey': 'library-music',
  'client.PotPlayer_global_pause_hotkey': 'live-tv',
  'client.foobar2000_global_pause_hotkey': 'headphones',
  'client.hint_while_recording_at_edit_position_powered_by_ahk': 'edit-note',
  'client.hint_while_recording_at_cursor_position': 'mouse',
  'client.check_microphone_usage_by': 'hearing',
  'client.hot_rag': 'auto-awesome',
  'client.hot_zh': 'tag',
  'client.多音字': 'dictionary',
  'client.声调': 'equalizer',
  'client.hot_en': 'label',
  'client.hot_rule': 'rule',
  'client.hot_kwd': 'bookmark',
  'client.arabic_year_number': 'numbers',
  'client.save_audio': 'save',
  'client.audio_name_len': 'format-size',
  'client.reduce_audio_files': 'compress',
  'client.save_markdown': 'description',
  'client.save_non_kwd_markdown': 'notes',

  // ── 客户端：简繁转换 ──
  'client.convert_to_traditional_chinese_main': 'translate',
  'client.enable_double_click_opposite_state': 'touch-app',
  'client.opencc_converter': 'sync',

  // ── 客户端：离线翻译 ──
  'client.use_offline_translate_function': 'cloud-off',
  'client.offline_translate_port': 'settings-ethernet',
  'client.offline_translate_shortcut': 'keyboard',
  'client.offline_translate_port_gemma2b': 'psychology',

  // ── 客户端：在线翻译 ──
  'client.use_online_translate_function': 'cloud',
  'client.online_translate_shortcut': 'keyboard',
  'client.online_translate_target_languages_libretranslate': 'language',
  'client.online_translate_target_languages': 'g-translate',

  // ── 客户端：文件转录 ──
  'client.use_hot_sub_when_transcribe_file': 'auto-awesome',
  'client.file_seg_duration': 'timer',
  'client.file_seg_overlap': 'layers',
  'client.file_save_srt': 'subtitles',
  'client.file_save_txt': 'subject',
  'client.file_save_json': 'data-object',
  'client.file_save_merge': 'merge',

  // ── 客户端：AI 优化 ──
  'client.enable_ai_optimize_language_expression': 'auto-awesome',
  'client.ai_provider': 'smart-toy',
  'client.prompt_style_selection': 'style',
  'client.show_prompt_style_changed_notification': 'notifications',
  'client.show_time_label': 'schedule',

  // ── AI 服务商 ──
  'client.openai.api_key': 'vpn-key',
  'client.openai.base_url': 'link',
  'client.openai.model': 'model-training',
  'client.zhipuai.api_key': 'vpn-key',
  'client.zhipuai.model': 'model-training',

  // ── 提示风格：8 种风格各自一个意象 + 统一的快捷键图标 ──
  'client.prompt_style.prompt_official': 'description',
  'client.prompt_style.prompt_official_shortcut': 'keyboard',
  'client.prompt_style.prompt_sweetheart': 'favorite',
  'client.prompt_style.prompt_sweetheart_shortcut': 'keyboard',
  'client.prompt_style.prompt_social': 'share',
  'client.prompt_style.prompt_social_shortcut': 'keyboard',
  'client.prompt_style.prompt_poetry': 'brush',
  'client.prompt_style.prompt_poetry_shortcut': 'keyboard',
  'client.prompt_style.prompt_english': 'translate',
  'client.prompt_style.prompt_english_shortcut': 'keyboard',
  'client.prompt_style.prompt_academic': 'school',
  'client.prompt_style.prompt_academic_shortcut': 'keyboard',
  'client.prompt_style.prompt_customer_service': 'support-agent',
  'client.prompt_style.prompt_customer_service_shortcut': 'keyboard',
  'client.prompt_style.prompt_creative_writing': 'edit-note',
  'client.prompt_style.prompt_creative_writing_shortcut': 'keyboard',

  // ── 附加特殊应用 ──
  'client.additional_special_apps': 'apps',

  // ── LibreTranslate ──
  'libretranslate.api': 'cloud',

  // ── DeepLX ──
  'deeplx.online_translate_port': 'settings-ethernet',
  'deeplx.exe_path': 'terminal',
  'deeplx.api': 'cloud',

  // ── 模型路径 ──
  'model_paths.model_dir': 'folder',
  'model_paths.punc_model_dir': 'folder-open',
  'model_paths.funasr_dir': 'folder',
  'model_paths.funasr_encoder_adaptor_path': 'file-present',
  'model_paths.funasr_ctc_path': 'bolt',
  'model_paths.funasr_llm_path': 'psychology',
  'model_paths.funasr_tokens_path': 'text-fields',
  'model_paths.funasr_hotwords_path': 'tag',
  'model_paths.sensevoice_path': 'file-present',
  'model_paths.sensevoice_tokens_path': 'text-fields',
  'model_paths.paraformer_path': 'file-present',
  'model_paths.paraformer_tokens_path': 'text-fields',
  'model_paths.qwen_ctc_encoder_path': 'file-present',
  'model_paths.qwen_ctc_ctc_path': 'bolt',
  'model_paths.qwen_ctc_tokens_path': 'text-fields',
  'model_paths.qwen_ctc_preprocessor_path': 'folder',
  'model_paths.qwen_llm_path': 'psychology',
  'model_paths.qwen_ctc_encoder_frontend_path': 'file-present',
  'model_paths.qwen_ctc_encoder_backend_path': 'file-present',
  'model_paths.opus_mt_dir': 'translate',

  // ── FunASR 参数（含 5 个派生只读键） ──
  'funasr_args.encoder_onnx_path': 'file-present',
  'funasr_args.ctc_onnx_path': 'bolt',
  'funasr_args.decoder_gguf_path': 'psychology',
  'funasr_args.tokens_path': 'text-fields',
  'funasr_args.hotwords_path': 'tag',
  'funasr_args.enable_ctc': 'bolt',
  'funasr_args.n_predict': 'numbers',
  'funasr_args.n_threads': 'memory',
  'funasr_args.similar_threshold': 'percent',
  'funasr_args.max_hotwords': 'tag',
  'funasr_args.directml_enable': 'developer-board',
  'funasr_args.vulkan_enable': 'bolt',
  'funasr_args.vulkan_force_fp32': 'precision-manufacturing',
  'funasr_args.flash_attn': 'speed',
  'funasr_args.verbose': 'subject',

  // ── SenseVoice 参数 ──
  'sensevoice_args.model': 'file-present',
  'sensevoice_args.tokens': 'text-fields',
  'sensevoice_args.num_threads': 'memory',
  'sensevoice_args.sample_rate': 'graphic-eq',
  'sensevoice_args.feature_dim': 'straighten',
  'sensevoice_args.decoding_method': 'tune',
  'sensevoice_args.debug': 'bug-report',
  'sensevoice_args.provider': 'computer',
  'sensevoice_args.language': 'language',
  'sensevoice_args.use_itn': 'numbers',
  'sensevoice_args.rule_fsts': 'rule',
  'sensevoice_args.rule_fars': 'checklist',

  // ── Paraformer 参数 ──
  'paraformer_args.paraformer': 'file-present',
  'paraformer_args.tokens': 'text-fields',
  'paraformer_args.num_threads': 'memory',
  'paraformer_args.sample_rate': 'graphic-eq',
  'paraformer_args.feature_dim': 'straighten',
  'paraformer_args.decoding_method': 'tune',
  'paraformer_args.debug': 'bug-report',

  // ── QwenCTC 参数（含 4 个派生只读键） ──
  'qwen_ctc_args.encoder_onnx_path': 'file-present',
  'qwen_ctc_args.ctc_onnx_path': 'bolt',
  'qwen_ctc_args.tokens_path': 'text-fields',
  'qwen_ctc_args.preprocessor_path': 'folder',
  'qwen_ctc_args.decoder_gguf_path': 'psychology',
  'qwen_ctc_args.encoder_frontend_path': 'file-present',
  'qwen_ctc_args.encoder_backend_path': 'file-present',
  'qwen_ctc_args.blank_id': 'numbers',
  'qwen_ctc_args.unk_id': 'numbers',
  'qwen_ctc_args.mel_frames': 'straighten',
  'qwen_ctc_args.num_threads': 'memory',
  'qwen_ctc_args.provider': 'computer',
  'qwen_ctc_args.start_bias': 'timer',
  'qwen_ctc_args.end_bias': 'timer',
  'qwen_ctc_args.enable_ctc': 'bolt',
  'qwen_ctc_args.llm_n_ctx': 'numbers',
  'qwen_ctc_args.llm_n_threads': 'memory',
  'qwen_ctc_args.llm_n_predict': 'numbers',
  'qwen_ctc_args.verbose': 'subject',

  // ── 调试 ──
  'debug.logger_level': 'terminal',
};

/**
 * 新字段万一忘了登记，也不能让界面露出一个空洞：按控件类型给个合理的图形。
 * 这条兜底不是「允许不登记」——`fieldIcons.test.ts` 会对现有 161 项逐个断言
 * 必须命中 `FIELD_ICONS`，兜底只服务于以后新增字段的那几分钟。
 */
export const FALLBACK_BY_WIDGET: Record<WidgetKind, string> = {
  text: 'text-fields',
  int: 'numbers',
  float: 'numbers',
  bool: 'toggle-on',
  enum: 'list',
  path: 'folder',
  hotkey: 'keyboard',
  stringList: 'format-list-bulleted',
  pairList: 'list',
  longText: 'subject',
  secret: 'vpn-key',
  readonly: 'link',
  dynamicTable: 'table-chart',
};

/**
 * 兜底用到的图标名。测试拿它区分「登记了但没人用」和「只给兜底用」——
 * 后者本来就该留在登记表里，否则 `ICONS[name]` 会取到 undefined。
 */
export const FALLBACK_SAMPLE: string[] = [...new Set([...Object.values(FALLBACK_BY_WIDGET), 'info'])];

/**
 * 图标名（kebab）。给只需要「名字」的地方用，比如搜索结果把图标名当数据带着走，
 * 由渲染方去 `ICONS[name]` 取图形。
 */
export function iconNameForField(field: Pick<FieldMeta, 'path' | 'widget'>): string {
  return FIELD_ICONS[field.path] ?? FALLBACK_BY_WIDGET[field.widget] ?? 'info';
}

/** 取某个配置项的图标；`name` 一定能在 `ICONS` 里查到（兜底项也登记了） */
export function iconForField(field: Pick<FieldMeta, 'path' | 'widget'>): IconifyIcon {
  return ICONS[iconNameForField(field)] ?? info;
}
