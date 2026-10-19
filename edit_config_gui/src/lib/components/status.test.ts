/**
 * 状态栏、重启确认与「没找到配置」引导。
 *
 * 重启这条路径值得写测试的原因不是代码复杂，而是它的失败方式很安静：`restart_service`
 * 在降权失败时**仍然会启动进程**（用继承的高权限令牌），只是客户端连不上它。
 * 如果前端不把这个 `degraded` 显示出来，用户会以为「重启成功了但语音坏了」。
 */
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { fireEvent, render, screen } from '@testing-library/svelte';

import App from '../../App.svelte';
import Onboarding from './Onboarding.svelte';
import StatusBar from './StatusBar.svelte';

/*
 * m3-svelte 的入口会连带求值 Slider（→ svelte/motion），后者在模块顶层读
 * matchMedia 来跟踪 prefers-reduced-motion；jsdom 没实现这个 API。
 * 用 vi.hoisted 保证补丁先于任何 import 生效。
 */
vi.hoisted(() => {
  if (typeof window === 'undefined' || typeof window.matchMedia === 'function') return;
  window.matchMedia = (query: string): MediaQueryList =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList;
});

// jsdom 30 的 HTMLDialogElement 只是个空壳，没有 showModal()/close()，而 m3 的
// Dialog 一挂载就会调用它们。补一个最小实现，让组件树能挂载、open 属性生效。
if (typeof HTMLDialogElement !== 'undefined') {
  HTMLDialogElement.prototype.showModal = function (this: HTMLDialogElement): void {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function (this: HTMLDialogElement): void {
    this.open = false;
  };
}

const mocks = vi.hoisted(() => ({
  openConfig: vi.fn(),
  reloadConfig: vi.fn(),
  previewSave: vi.fn(),
  commitSave: vi.fn(),
  pickPath: vi.fn(),
  runningProcesses: vi.fn(),
  restartService: vi.fn(),
  restartServiceElevated: vi.fn(),
}));

vi.mock('../../bridge.ts', () => ({ bridge: mocks }));

function running(over: Record<string, unknown> = {}): void {
  mocks.runningProcesses.mockResolvedValue({
    server: true,
    client: false,
    clientVariant: null,
    isAdmin: false,
    clientAdmin: false,
    serverAdmin: false,
    ...over,
  });
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('StatusBar', () => {
  it('服务端在跑时显示运行指示与重启按钮', async () => {
    running();
    render(StatusBar);

    expect(await screen.findByText('服务端')).toBeTruthy();
    expect(screen.getByLabelText('服务端运行中')).toBeTruthy();
    expect(screen.getByLabelText('客户端未运行')).toBeTruthy();
    // 没在跑的进程不给重启按钮：重启一个没启动的服务端，用户多半是想「启动」，
    // 而启动要的不是 restart_service 的语义
    expect(screen.queryByRole('button', { name: /重启客户端/ })).toBeNull();
  });

  it('点重启先弹确认，确认后才调 restart_service', async () => {
    running();
    mocks.restartService.mockResolvedValue({ degraded: false });
    render(StatusBar);

    await fireEvent.click(await screen.findByRole('button', { name: '重启服务端' }));
    expect(screen.getByText(/重启会中断正在进行的语音输入/)).toBeTruthy();
    expect(mocks.restartService).not.toHaveBeenCalled();

    await fireEvent.click(screen.getByRole('button', { name: '确认重启' }));
    expect(mocks.restartService).toHaveBeenCalledWith('server');
  });

  it('取消确认时不调 restart_service', async () => {
    running();
    render(StatusBar);

    await fireEvent.click(await screen.findByRole('button', { name: '重启服务端' }));
    await fireEvent.click(screen.getByRole('button', { name: '取消' }));

    expect(mocks.restartService).not.toHaveBeenCalled();
    expect(screen.queryByText(/重启会中断正在进行的语音输入/)).toBeNull();
  });

  it('degraded=true 时明确提示降权失败', async () => {
    running({ isAdmin: true });
    mocks.restartService.mockResolvedValue({ degraded: true });
    render(StatusBar);

    await fireEvent.click(await screen.findByRole('button', { name: '重启服务端' }));
    await fireEvent.click(screen.getByRole('button', { name: '确认重启' }));

    expect(await screen.findByText(/未能以普通权限启动/)).toBeTruthy();
  });

  it('重启失败时显示后端文案而不是静默', async () => {
    running();
    mocks.restartService.mockRejectedValue('进程已在运行');
    render(StatusBar);

    await fireEvent.click(await screen.findByRole('button', { name: '重启服务端' }));
    await fireEvent.click(screen.getByRole('button', { name: '确认重启' }));

    expect(await screen.findByText(/重启失败：进程已在运行/)).toBeTruthy();
  });

  it('客户端以管理员权限运行时圆点变紫色并换 aria-label', async () => {
    running({ client: true, clientAdmin: true });
    render(StatusBar);

    const dot = await screen.findByLabelText('客户端以管理员权限运行');
    expect(dot.classList.contains('admin')).toBe(true);
    expect(screen.queryByLabelText('客户端运行中')).toBeNull();
  });

  it('普通权限的客户端圆点不带紫色 class', async () => {
    running({ client: true, clientAdmin: false });
    render(StatusBar);

    const dot = await screen.findByLabelText('客户端运行中');
    expect(dot.classList.contains('admin')).toBe(false);
  });

  it('服务端以管理员权限运行时圆点变紫色并换 aria-label', async () => {
    running({ serverAdmin: true });
    render(StatusBar);

    const dot = await screen.findByLabelText('服务端以管理员权限运行');
    expect(dot.classList.contains('admin')).toBe(true);
    expect(screen.queryByLabelText('服务端运行中')).toBeNull();
  });

  it('普通权限的服务端圆点不带紫色 class', async () => {
    running({ serverAdmin: false });
    render(StatusBar);

    const dot = await screen.findByLabelText('服务端运行中');
    expect(dot.classList.contains('admin')).toBe(false);
  });

  it('客户端管理员且管理器未提权时，确认框先给出提权预提示', async () => {
    running({ client: true, clientAdmin: true, isAdmin: false });
    render(StatusBar);

    await fireEvent.click(await screen.findByRole('button', { name: '重启客户端' }));

    expect(screen.getByText('客户端以管理员权限运行，重启需要提权（会弹出 UAC 确认）')).toBeTruthy();
  });

  it('服务端管理员且管理器未提权时，确认框先给出提权预提示', async () => {
    running({ serverAdmin: true, isAdmin: false });
    render(StatusBar);

    await fireEvent.click(await screen.findByRole('button', { name: '重启服务端' }));

    expect(screen.getByText('服务端以管理员权限运行，重启需要提权（会弹出 UAC 确认）')).toBeTruthy();
  });

  it('服务端未提权而客户端提权时，服务端不显示提权提示、圆点也不带紫色', async () => {
    running({ server: true, client: true, serverAdmin: false, clientAdmin: true, isAdmin: false });
    render(StatusBar);

    const serverDot = await screen.findByLabelText('服务端运行中');
    expect(serverDot.classList.contains('admin')).toBe(false);
    expect(await screen.findByLabelText('客户端以管理员权限运行')).toBeTruthy();

    await fireEvent.click(screen.getByRole('button', { name: '重启服务端' }));

    expect(screen.queryByText('服务端以管理员权限运行，重启需要提权（会弹出 UAC 确认）')).toBeNull();
  });

  it('needsElevation=true 时对话框不关闭，停在提权阶段且未调 restart_service_elevated', async () => {
    running({ client: true, clientAdmin: true });
    mocks.restartService.mockResolvedValue({ degraded: false, needsElevation: true });
    render(StatusBar);

    await fireEvent.click(await screen.findByRole('button', { name: '重启客户端' }));
    await fireEvent.click(screen.getByRole('button', { name: '确认重启' }));

    expect(await screen.findByRole('button', { name: '以管理员权限重启' })).toBeTruthy();
    // m3 的 Dialog 用 role="alertdialog"：确认框是「必须回应才能继续」的模态，
    // 比普通 dialog 更准确，读屏软件也会把整个内容念一遍。
    expect(screen.getByRole('alertdialog')).toBeTruthy();
    expect(screen.queryByRole('button', { name: '确认重启' })).toBeNull();
    expect(mocks.restartServiceElevated).not.toHaveBeenCalled();
  });

  it('提权阶段点「以管理员权限重启」才对 client 调 restart_service_elevated', async () => {
    running({ client: true, clientAdmin: true });
    mocks.restartService.mockResolvedValue({ degraded: false, needsElevation: true });
    mocks.restartServiceElevated.mockResolvedValue({ degraded: false, needsElevation: false });
    render(StatusBar);

    await fireEvent.click(await screen.findByRole('button', { name: '重启客户端' }));
    await fireEvent.click(screen.getByRole('button', { name: '确认重启' }));
    await fireEvent.click(await screen.findByRole('button', { name: '以管理员权限重启' }));

    expect(mocks.restartServiceElevated).toHaveBeenCalledWith('client');
    expect(screen.queryByRole('alertdialog')).toBeNull();
  });

  it('提权重启失败时显示重启失败文案', async () => {
    running({ client: true, clientAdmin: true });
    mocks.restartService.mockResolvedValue({ degraded: false, needsElevation: true });
    mocks.restartServiceElevated.mockRejectedValue('用户拒绝了 UAC');
    render(StatusBar);

    await fireEvent.click(await screen.findByRole('button', { name: '重启客户端' }));
    await fireEvent.click(screen.getByRole('button', { name: '确认重启' }));
    await fireEvent.click(await screen.findByRole('button', { name: '以管理员权限重启' }));

    expect(await screen.findByText(/重启失败：用户拒绝了 UAC/)).toBeTruthy();
  });
});

describe('Onboarding', () => {
  it('引导态不渲染导航，只渲染引导页', () => {
    render(App, { props: { __forceState: 'onboarding' } });

    expect(screen.getByText(/未找到 config.toml/)).toBeTruthy();
    expect(screen.queryByRole('tablist')).toBeNull();
  });

  it('手动选择文件后走 configStore.load，从而调用 open_config', async () => {
    mocks.pickPath.mockResolvedValue('D:\\x\\config.toml');
    mocks.openConfig.mockResolvedValue({
      path: 'D:\\x\\config.toml',
      fingerprint: { mtimeMs: 1, size: 2, sha256: 'x' },
      fields: [],
      baseDir: 'D:\\x',
    });

    render(Onboarding);
    await fireEvent.click(screen.getByRole('button', { name: /选择 config.toml/ }));

    expect(mocks.pickPath).toHaveBeenCalledWith('file', expect.any(String));
    expect(mocks.openConfig).toHaveBeenCalledWith('D:\\x\\config.toml');
  });

  it('用户取消选择时不发 open_config', async () => {
    mocks.pickPath.mockResolvedValue(null);

    render(Onboarding);
    await fireEvent.click(screen.getByRole('button', { name: /选择 config.toml/ }));

    expect(mocks.openConfig).not.toHaveBeenCalled();
  });
});
