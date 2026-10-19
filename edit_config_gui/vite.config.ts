import { defineConfig } from 'vitest/config';   // 不是 'vite'：否则 test 字段过不了类型检查
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';
import { functionsMixins } from 'vite-plugin-functions-mixins';

export default defineConfig({
  // svelteTesting() 只在 vitest 下生效：它把 resolve.conditions 切到 browser。
  // 不加会把 `svelte` 解析到 index-server.js，组件测试全部报
  // `lifecycle_function_unavailable: mount(...) is not available on the server`。
  // 它还带 autoCleanup，省掉每个测试文件手写 cleanup()。
  //
  // functionsMixins() 是 m3-svelte 的构建期依赖：`m3-svelte/etc/styles.css` 里用
  // `@apply --m3-*` / `--translucent(…)` 写焦点环和高度阴影，这些是 CSS 草案语法，
  // 浏览器不认，必须在这里展开成普通声明。`deps: ['m3-svelte']` 是必须的——插件只在
  // 「项目目录」和列出的依赖里找 @mixin/@function 定义，而定义恰好就在 m3-svelte 里。
  plugins: [functionsMixins({ deps: ['m3-svelte'] }), svelte(), svelteTesting()],
  clearScreen: false,
  server: { port: 1420, strictPort: true, watch: { ignored: ['**/src-tauri/**'] } },
  build: { target: 'chrome110', emptyOutDir: true, sourcemap: false },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
});
