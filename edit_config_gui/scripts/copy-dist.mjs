/**
 * 把 release 产物复制到仓库根。
 *
 * 为什么不直接用 tauri 的 bundle：我们只要一个裸 exe（前端资源已内嵌），
 * `bundle.active` 因此是 false。但 `tauri build` 仍然把可执行文件放在
 * `src-tauri/target/release/`，而用户和 `dev/archive_list.txt` 都期望它在仓库根、
 * 和 play 脚本放一起。
 */
import { copyFileSync, existsSync, statSync } from 'node:fs';

const src = new URL('../src-tauri/target/release/edit_config_gui.exe', import.meta.url);
const dst = new URL('../../edit_config_gui.exe', import.meta.url);

if (!existsSync(src)) {
  console.error('未找到构建产物：', src.pathname);
  console.error('先跑 pnpm build:tauri（或直接 pnpm build:dist）');
  process.exit(1);
}

copyFileSync(src, dst);
const mb = (statSync(dst).size / 1024 / 1024).toFixed(1);
console.log(`已复制到仓库根：edit_config_gui.exe（${mb} MB）`);
