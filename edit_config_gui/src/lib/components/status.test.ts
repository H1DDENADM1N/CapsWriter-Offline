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

const mocks = vi.hoisted(() => ({
  openConfig: vi.fn(),
  reloadConfig: vi.fn(),
  previewSave: vi.fn(),
  commitSave: vi.fn(),
  pickPath: vi.fn(),
  runningProcesses: vi.fn(),
  restartService: vi.fn(),
}));

vi.mock('../../bridge.ts', () => ({ bridge: mocks }));

function running(over: Record<string, unknown> = {}): void {
  mocks.runningProcesses.mockResolvedValue({
    server: true,
    client: false,
    clientVariant: null,
    isAdmin: false,
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
