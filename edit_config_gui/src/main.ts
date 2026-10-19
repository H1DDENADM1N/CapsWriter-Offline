import { mount } from 'svelte';

// 顺序有意义：m3 的样式表先落地（组件依赖 --m3-* 形状/高度令牌），
// 本应用的 app.css 后加载，才能在令牌层覆盖它。
import '../node_modules/m3-svelte/package/etc/styles.css';
import 'm3-svelte/etc/layer';
import './app.css';

import App from './App.svelte';
import { themeStore } from './lib/stores/theme.svelte.ts';
import { zoomStore } from './lib/stores/zoom.svelte.ts';

// 必须在 mount 之前：主题令牌是运行时按 Windows 主题色生成、注入 <style> 的，
// 晚一步就会先闪一帧默认配色。
themeStore.start();

// 缩放监听也提前装：Ctrl+= 在首帧之后才按下去的概率更高，但装上更省心
zoomStore.start();

export default mount(App, { target: document.getElementById('app')! });
