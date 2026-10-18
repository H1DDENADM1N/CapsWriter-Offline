import { defineConfig } from 'vitest/config';   // 不是 'vite'：否则 test 字段过不了类型检查
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  clearScreen: false,
  server: { port: 1420, strictPort: true, watch: { ignored: ['**/src-tauri/**'] } },
  build: { target: 'chrome110', emptyOutDir: true, sourcemap: false },
  test: { environment: 'jsdom', include: ['src/**/*.test.ts'] },
});
