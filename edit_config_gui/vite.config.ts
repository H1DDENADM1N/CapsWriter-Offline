import { defineConfig } from 'vitest/config';   // 不是 'vite'：否则 test 字段过不了类型检查
import { svelte } from '@sveltejs/vite-plugin-svelte';
import { svelteTesting } from '@testing-library/svelte/vite';

export default defineConfig({
  // svelteTesting() 只在 vitest 下生效：它把 resolve.conditions 切到 browser。
  // 不加会把 `svelte` 解析到 index-server.js，组件测试全部报
  // `lifecycle_function_unavailable: mount(...) is not available on the server`。
  // 它还带 autoCleanup，省掉每个测试文件手写 cleanup()。
  plugins: [svelte(), svelteTesting()],
  clearScreen: false,
  server: { port: 1420, strictPort: true, watch: { ignored: ['**/src-tauri/**'] } },
  build: { target: 'chrome110', emptyOutDir: true, sourcemap: false },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
});
