import { describe, expect, it, vi, beforeEach } from 'vitest';

const setZoom = vi.fn((_scale: number) => Promise.resolve());

vi.mock('../../bridge.ts', () => ({
  bridge: {
    setZoom: (scale: number) => setZoom(scale),
  },
}));

const { DEFAULT_ZOOM, ZOOM_STEPS, nextZoom, zoomPercent, zoomStore } = await import('./zoom.svelte.ts');

describe('nextZoom', () => {
  it('从 100% 往上是 110%，往下是 90%', () => {
    expect(nextZoom(1, 1)).toBe(1.1);
    expect(nextZoom(1, -1)).toBe(0.9);
  });

  it('走到两端就停住，不回卷', () => {
    expect(nextZoom(2, 1)).toBe(2);
    expect(nextZoom(0.5, -1)).toBe(0.5);
  });

  it('当前值不在档位上时按大小落到相邻档，而不是弹回 100%', () => {
    expect(nextZoom(1.05, 1)).toBe(1.1);
    expect(nextZoom(1.05, -1)).toBe(1);
    expect(nextZoom(0.72, -1)).toBe(0.67);
  });

  it('档位是严格递增的，且包含 100% 与两端', () => {
    for (let i = 1; i < ZOOM_STEPS.length; i += 1) {
      expect(ZOOM_STEPS[i]).toBeGreaterThan(ZOOM_STEPS[i - 1]);
    }
    expect(ZOOM_STEPS).toContain(DEFAULT_ZOOM);
    expect(ZOOM_STEPS[0]).toBe(0.5);
    expect(ZOOM_STEPS[ZOOM_STEPS.length - 1]).toBe(2);
  });
});

describe('zoomPercent', () => {
  it('四舍五入成整数百分比', () => {
    expect(zoomPercent(1)).toBe(100);
    expect(zoomPercent(0.67)).toBe(67);
    expect(zoomPercent(1.25)).toBe(125);
  });
});

describe('zoomStore', () => {
  beforeEach(() => {
    zoomStore.__resetForTest();
    setZoom.mockClear();
  });

  it('默认 100%，且判定为「未缩放」', () => {
    expect(zoomStore.current()).toBe(1);
    expect(zoomStore.percent()).toBe(100);
    expect(zoomStore.isDefault()).toBe(true);
  });

  it('放大 / 缩小走档位，并把比例交给 webview', () => {
    zoomStore.zoomIn();
    expect(zoomStore.current()).toBe(1.1);
    expect(zoomStore.isDefault()).toBe(false);
    expect(setZoom).toHaveBeenLastCalledWith(1.1);

    zoomStore.zoomOut();
    expect(zoomStore.current()).toBe(1);
    expect(setZoom).toHaveBeenLastCalledWith(1);
  });

  it('连续放大到上限后停住，不会越界', () => {
    for (let i = 0; i < 20; i += 1) zoomStore.zoomIn();
    expect(zoomStore.current()).toBe(2);
  });

  it('还原回到 100% 且重新判定为默认', () => {
    zoomStore.zoomOut();
    zoomStore.zoomOut();
    expect(zoomStore.current()).toBe(0.8);
    zoomStore.reset();
    expect(zoomStore.current()).toBe(1);
    expect(zoomStore.isDefault()).toBe(true);
  });

  it('已经是 100% 时再还原不发请求', () => {
    zoomStore.reset();
    expect(setZoom).not.toHaveBeenCalled();
  });

  /*
   * 下面两条走真实的 window 监听器：快捷键和滚轮是「装了但没接上」最容易漏的
   * 那类 bug——状态机单测全绿，用户按下去却什么都没发生。
   */
  it('Ctrl+= 放大、Ctrl+- 缩小，且吃掉默认行为（WebView2 不能自己再缩一次）', () => {
    zoomStore.start();

    const down = new KeyboardEvent('keydown', { key: '=', ctrlKey: true, cancelable: true });
    window.dispatchEvent(down);
    expect(zoomStore.current()).toBe(1.1);
    expect(down.defaultPrevented).toBe(true);

    const up = new KeyboardEvent('keydown', { key: '-', ctrlKey: true, cancelable: true });
    window.dispatchEvent(up);
    expect(zoomStore.current()).toBe(1);
  });

  it('Ctrl+0 回到 100%，不带 Ctrl 的等号不触发', () => {
    zoomStore.start();
    zoomStore.zoomIn();
    zoomStore.zoomIn();
    expect(zoomStore.current()).toBe(1.25);

    window.dispatchEvent(new KeyboardEvent('keydown', { key: '0', ctrlKey: true, cancelable: true }));
    expect(zoomStore.current()).toBe(1);

    window.dispatchEvent(new KeyboardEvent('keydown', { key: '=', cancelable: true }));
    expect(zoomStore.current()).toBe(1);
  });

  it('Ctrl+滚轮一格一档，并阻止页面滚动', () => {
    zoomStore.start();

    const wheel = new WheelEvent('wheel', { deltaY: -100, ctrlKey: true, cancelable: true });
    window.dispatchEvent(wheel);

    expect(zoomStore.current()).toBe(1.1);
    expect(wheel.defaultPrevented).toBe(true);

    // 不按 Ctrl 的滚轮交给页面自己滚
    const plain = new WheelEvent('wheel', { deltaY: 100, cancelable: true });
    window.dispatchEvent(plain);
    expect(plain.defaultPrevented).toBe(false);
    expect(zoomStore.current()).toBe(1.1);
  });
});
