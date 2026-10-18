<script lang="ts">
  /**
   * 内联 SVG 图标。
   *
   * 不用图标字体也不用图标包：13 个导航图标加起来不到 2 KB，而一个图标字体
   * 要额外拉一份 woff2、还要处理 FOIT/FOUT；图标包里几千个图标里我们只用 10 个。
   *
   * 全部 `stroke="currentColor"`，颜色跟着文字走——这样深色模式不需要为图标
   * 再做一套。
   */
  let { name, size = 16 }: { name: string; size?: number } = $props();

  const PATHS: Record<string, string> = {
    // 服务端：两台堆叠的机器
    server: 'M3.5 4.5h17v5h-17zM3.5 14.5h17v5h-17zM6.5 7h.01M6.5 17h.01',
    // 客户端：显示器
    client: 'M3.5 4.5h17v11h-17zM9 19.5h6M12 15.5v4',
    // AI：四角星
    ai: 'M12 3.2l1.7 4.4 4.4 1.7-4.4 1.7-1.7 4.4-1.7-4.4-4.4-1.7 4.4-1.7zM18.5 16.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z',
    // 提示风格：调色板
    palette:
      'M12 3.2a8.8 8.8 0 100 17.6h1.2a1.9 1.9 0 001.6-3 1.9 1.9 0 011.6-3h2.2a2.2 2.2 0 002.2-2.2A8.8 8.8 0 0012 3.2zM7.6 9.4h.01M11 7.2h.01M15 8.6h.01',
    // 翻译：两种文字的箭头
    translate:
      'M3.8 5.4h8.4M8 5.4v1.7c0 3.6-1.9 5.6-4.2 6.6M5.6 9.2c1 2.7 3.1 4.4 5.9 5.3M13.2 19.6l3.8-9.6 3.8 9.6M14.6 16.6h4.8',
    // 模型参数：CPU
    cpu: 'M7 7h10v10H7zM10 10h4v4h-4zM3.8 10H7M3.8 14H7M17 10h3.2M17 14h3.2M10 3.8V7M14 3.8V7M10 17v3.2M14 17v3.2',
    // 模型路径：文件夹
    folder: 'M3.4 7.4a1.8 1.8 0 011.8-1.8h3.6l2 2h7.8a1.8 1.8 0 011.8 1.8v7.4a1.8 1.8 0 01-1.8 1.8H5.2a1.8 1.8 0 01-1.8-1.8z',
    // 调试：虫子
    bug: 'M9.2 5.4a2.8 2.8 0 015.6 0M6.4 9.2h11.2M6.4 13h11.2M6.4 16.8h11.2M12 9.2v9.4M8.6 5.6L6.8 3.8M15.4 5.6l1.8-1.8M8.6 18.6l-1.8 1.8M15.4 18.6l1.8 1.8',
    // 关于：信息
    info: 'M12 3.4a8.6 8.6 0 100 17.2 8.6 8.6 0 000-17.2zM12 11v5.4M12 7.8h.01',
    // 其它应用：网格
    app: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  };
</script>

<svg
  width={size}
  height={size}
  viewBox="0 0 24 24"
  fill="none"
  stroke="currentColor"
  stroke-width="1.6"
  stroke-linecap="round"
  stroke-linejoin="round"
  aria-hidden="true"
  focusable="false"
>
  <path d={PATHS[name] ?? PATHS.info} />
</svg>
