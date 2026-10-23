<#
.SYNOPSIS
  重新构建配置管理器 edit_config_gui.exe，并覆盖仓库根目录下的同名文件。

.DESCRIPTION
  构建方法取自 edit_config_gui\README.md 的「常用命令」一节，脚本只是把它固化成
  一条带前置检查与后置校验的流程：

      cd edit_config_gui
      pnpm install          # node_modules 缺失或显式 -Install 时才跑
      pnpm build:dist       # = tauri build && node scripts/copy-dist.mjs

  bundle.active 为 false，前端资源由 Tauri 内嵌进 exe，所以产物是单文件：

      edit_config_gui\src-tauri\target\release\edit_config_gui.exe   编译产物
      edit_config_gui.exe                                            复制到仓库根（本脚本要覆盖的）

  流程：
    1. 校验目录结构、icons\icon.ico（tauri-build 生成 Windows 资源文件必须要有它）
    2. 解析工具链：cargo（不在 PATH 时补 %USERPROFILE%\.cargo\bin）、node、pnpm；
       版本低于 README 要求只警告不阻断（cargo 会按 Cargo.toml 的 rust-version 自己报错）
    3. 检查 WebView2 Runtime（运行期依赖，缺失只警告）
    4. 处理「仓库根 exe 正被占用」——这是 README 里记录的 EBUSY 坑：
       管理器开着时 Rust 编译会成功，但 copy-dist.mjs 复制不进去。
       默认报错让人先关窗口；加 -StopRunning 则由脚本结束进程（未保存的编辑会丢）
    5. 可选的质量门（-Check：pnpm check + pnpm test）、schema 重生成（-RegenSchema）
    6. pnpm build:dist，输出同时 tee 到 %TEMP% 下的日志
    7. 后置校验：产物确实是本次刷新的（mtime 晚于构建开始时间），且仓库根 exe 与
       编译产物的 SHA256 一致——以此证明「覆盖」真的发生了，而不是复制悄悄失败
    8. 打印产物路径、大小、时间、哈希与耗时

  退出码：0 成功；1 失败（每一步失败都会给出可操作的原因）。

.PARAMETER StopRunning
  构建前结束正在运行的 edit_config_gui 进程。
  不加这个开关时，检测到进程在跑会直接报错退出——不擅自杀掉用户开着的窗口，
  因为里面可能有没保存的改动。

.PARAMETER Install
  强制重跑 pnpm install --frozen-lockfile（默认只在 node_modules 缺失时跑）。

.PARAMETER Check
  构建前跑前端质量门：pnpm check（svelte-check，要求 0 error 0 warning）
  与 pnpm test（vitest）。失败则中止，不产出新 exe。
  注意：Rust 侧单测不在本开关范围内，需要时手动跑
  `cd edit_config_gui\src-tauri; cargo test --release`。

.PARAMETER RegenSchema
  构建前重跑 pnpm gen:schema-paths 与 node scripts/gen-pinyin-map.mjs。
  只有改过 src/lib/schema/*.ts 时才需要（见 README「改 schema 的注意事项」）。

.PARAMETER Backup
  覆盖前把当前的仓库根 edit_config_gui.exe 备份为 edit_config_gui.exe.bak。

.EXAMPLE
  .\dev\rebuild_edit_config_gui_exe.ps1
  常规重建。要求管理器已关闭。

.EXAMPLE
  .\dev\rebuild_edit_config_gui_exe.ps1 -StopRunning -Check -Backup
  关掉正在运行的管理器、先跑测试、保留旧 exe 备份，然后重建。

.NOTES
  脚本位于 <仓库根>\dev\，仓库根是它的上一级，所以所有路径都锚在
  (Split-Path -Parent $PSScriptRoot) 上并解析成绝对路径，可从任意当前目录调用。
  控制台按 UTF-8 输出，避免 cargo / pnpm 的中文提示变乱码。
#>
[CmdletBinding()]
param(
    [switch]$StopRunning,
    [switch]$Install,
    [switch]$Check,
    [switch]$RegenSchema,
    [switch]$Backup
)

$ErrorActionPreference = 'Stop'

# cargo / pnpm 的输出里有中文，控制台按 UTF-8 解码
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# ---- 路径：脚本在 dev\，仓库根是上一级 -------------------------------------
$repoRoot = Split-Path -Parent $PSScriptRoot
$projDir = Join-Path $repoRoot 'edit_config_gui'
$tauriDir = Join-Path $projDir 'src-tauri'
$outExe = Join-Path $repoRoot 'edit_config_gui.exe'
$outBak = Join-Path $repoRoot 'edit_config_gui.exe.bak'
$builtExe = Join-Path $tauriDir 'target\release\edit_config_gui.exe'
$iconIco = Join-Path $tauriDir 'icons\icon.ico'
$logPath = Join-Path $env:TEMP ('rebuild_edit_config_gui_{0}.log' -f (Get-Date -Format 'yyyyMMdd_HHmmss'))

$script:stepNo = 0
$sw = [System.Diagnostics.Stopwatch]::StartNew()

function Write-Step {
    param([string]$Text)
    $script:stepNo++
    Write-Host ''
    Write-Host ('[{0}] {1}' -f $script:stepNo, $Text) -ForegroundColor Cyan
}

function Write-Note {
    param([string]$Text)
    Write-Host ('    ' + $Text) -ForegroundColor DarkGray
}

function Write-Warn {
    param([string]$Text)
    Write-Host ('    ' + $Text) -ForegroundColor Yellow
}

function Fail {
    param([string]$Text)
    Write-Host ''
    Write-Host ('失败: ' + $Text) -ForegroundColor Red
    Write-Host ('耗时: {0:N1} 秒' -f $sw.Elapsed.TotalSeconds) -ForegroundColor DarkGray
    exit 1
}

# 打开文件做「读写 + 独占」探测：被运行中的 exe 占住时会抛异常
function Test-FileLocked {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return $false }
    try {
        $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $fs.Close()
        $fs.Dispose()
        return $false
    }
    catch { return $true }
}

function Get-EcgProcesses {
    return @(Get-Process -Name 'edit_config_gui' -ErrorAction SilentlyContinue)
}

function Test-MinVersion {
    param([string]$Found, [string]$Min)
    try { return ([version]$Found -ge [version]$Min) } catch { return $true }
}

# ---- 1) 目录结构 ----------------------------------------------------------
Write-Step '检查目录结构与构建必需文件'
foreach ($p in @($projDir, $tauriDir, (Join-Path $projDir 'package.json'),
        (Join-Path $tauriDir 'tauri.conf.json'))) {
    if (-not (Test-Path -LiteralPath $p)) { Fail "缺少必要路径：$p" }
}
if (-not (Test-Path -LiteralPath $iconIco)) {
    Fail "缺少 $iconIco。tauri-build 生成 Windows 资源文件必须要它（README「常见错误」第 1 条）。"
}
Write-Note "仓库根  : $repoRoot"
Write-Note "工程目录: $projDir"
Write-Note "目标产物: $outExe"

# ---- 2) 工具链 ------------------------------------------------------------
Write-Step '检查工具链（Rust / Node.js / pnpm）'

# Rust 没在 PATH 里时补 %USERPROFILE%\.cargo\bin
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    $cargoBin = Join-Path $env:USERPROFILE '.cargo\bin'
    if (Test-Path -LiteralPath (Join-Path $cargoBin 'cargo.exe')) {
        $env:PATH = "$cargoBin;$env:PATH"
        Write-Note "cargo 不在 PATH，已临时追加：$cargoBin"
    }
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Fail '找不到 cargo。先装 rustup（https://rustup.rs），或把 %USERPROFILE%\.cargo\bin 加进 PATH。'
}
if (-not (Get-Command rustc -ErrorAction SilentlyContinue)) {
    Fail '找不到 rustc。rustup 安装不完整，重装 rustup 工具链。'
}
$rustVerText = (& rustc --version) -join ' '
$rustVer = ($rustVerText -split '\s+')[1]
if (-not (Test-MinVersion -Found $rustVer -Min '1.95.0')) {
    Write-Warn "rustc $rustVer 低于 README 要求的 1.95（sysinfo 0.39 决定），cargo 可能直接报 rust-version 不满足。"
}

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail '找不到 node。需要 Node.js ≥ 20.19（构建期脚本用 node --experimental-strip-types 跑 .ts）。'
}
$nodeVer = (& node --version).TrimStart('v')
if (-not (Test-MinVersion -Found $nodeVer -Min '20.19.0')) {
    Write-Warn "node $nodeVer 低于 README 要求的 20.19。"
}

if (-not (Get-Command pnpm -ErrorAction SilentlyContinue)) {
    Fail '找不到 pnpm。用 `corepack enable pnpm` 或 `npm i -g pnpm` 安装（要求 ≥ 9）。'
}
$pnpmVer = (& pnpm --version)
Write-Note "rustc $rustVer / node $nodeVer / pnpm $pnpmVer"

# ---- 3) WebView2（运行期依赖，缺失只警告）---------------------------------
Write-Step '检查 WebView2 Runtime'
$wv2Keys = @(
    'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    'HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}',
    'HKCU:\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}'
)
$wv2Ver = $null
foreach ($k in $wv2Keys) {
    $v = (Get-ItemProperty -LiteralPath $k -Name 'pv' -ErrorAction SilentlyContinue).pv
    if ($v) { $wv2Ver = $v; break }
}
if ($wv2Ver) {
    Write-Note "WebView2 $wv2Ver"
}
else {
    Write-Warn '未检测到 WebView2 Runtime。不影响编译，但新 exe 启动会白屏——装 Evergreen Runtime 即可。'
}

# ---- 4) 占用处理 ----------------------------------------------------------
Write-Step '处理目标 exe 的占用状态'
$running = Get-EcgProcesses
if ($running.Count -gt 0) {
    $pids = ($running | ForEach-Object { $_.Id }) -join ', '
    if (-not $StopRunning) {
        Fail ("edit_config_gui 正在运行（PID $pids）。管理器开着时 Rust 编译会成功、但复制进仓库根会 EBUSY。`n" +
            "        先关掉窗口再重跑；或加 -StopRunning 让脚本结束它（未保存的编辑会丢失）。")
    }
    Write-Note "结束进程 PID $pids（-StopRunning）"
    foreach ($p in $running) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
    for ($i = 0; $i -lt 50; $i++) {
        if ((Get-EcgProcesses).Count -eq 0) { break }
        Start-Sleep -Milliseconds 100
    }
    if ((Get-EcgProcesses).Count -gt 0) {
        Fail '进程仍在运行，结束失败——多半是它以管理员权限启动，需用管理员 PowerShell 重跑本脚本。'
    }
}
if (Test-FileLocked -Path $outExe) {
    Fail "$outExe 被其它程序占用（进程名不是 edit_config_gui）。关闭占用它的程序（含预览窗格 / 杀软扫描）后重试。"
}
Write-Note '仓库根 exe 未被占用'

if ($Backup -and (Test-Path -LiteralPath $outExe)) {
    Copy-Item -LiteralPath $outExe -Destination $outBak -Force
    Write-Note "已备份旧 exe → $outBak"
}

# 之后所有命令都在工程目录里跑
Push-Location -LiteralPath $projDir
try {
    # ---- 5) 依赖安装 ------------------------------------------------------
    $needInstall = $Install -or (-not (Test-Path -LiteralPath (Join-Path $projDir 'node_modules')))
    if ($needInstall) {
        Write-Step 'pnpm install'
        if (Test-Path -LiteralPath (Join-Path $projDir 'pnpm-lock.yaml')) {
            & pnpm install --frozen-lockfile
        }
        else {
            & pnpm install
        }
        if ($LASTEXITCODE -ne 0) { Fail "pnpm install 失败（退出码 $LASTEXITCODE）" }
    }
    else {
        Write-Step '跳过 pnpm install（node_modules 已存在，需要时加 -Install）'
    }

    # ---- 6) 可选质量门 ----------------------------------------------------
    if ($RegenSchema) {
        Write-Step '重生成 schema 键清单与拼音表'
        & pnpm gen:schema-paths
        if ($LASTEXITCODE -ne 0) { Fail "pnpm gen:schema-paths 失败（退出码 $LASTEXITCODE）" }
        & node scripts/gen-pinyin-map.mjs
        if ($LASTEXITCODE -ne 0) { Fail "gen-pinyin-map.mjs 失败（退出码 $LASTEXITCODE）" }
    }

    if ($Check) {
        Write-Step 'pnpm check（svelte-check）'
        & pnpm check
        if ($LASTEXITCODE -ne 0) { Fail "pnpm check 失败（退出码 $LASTEXITCODE），未产出新 exe" }

        Write-Step 'pnpm test（vitest）'
        & pnpm test
        if ($LASTEXITCODE -ne 0) { Fail "pnpm test 失败（退出码 $LASTEXITCODE），未产出新 exe" }
    }

    # ---- 7) 构建 ----------------------------------------------------------
    Write-Step 'pnpm build:dist（tauri build + copy-dist.mjs）'
    Write-Note "日志: $logPath"
    $buildStart = Get-Date
    # PS 5.1 在 EAP=Stop 时会把原生命令的 stderr 当终止错误，构建期间临时放宽
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & pnpm build:dist 2>&1 | Tee-Object -FilePath $logPath
        $buildExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prevEap
    }

    # ---- 8) 校验 ----------------------------------------------------------
    Write-Step '校验产物'
    $builtFresh = $false
    if (Test-Path -LiteralPath $builtExe) {
        $builtFresh = (Get-Item -LiteralPath $builtExe).LastWriteTime -ge $buildStart
    }

    if ($buildExit -ne 0) {
        if (-not $builtFresh) {
            Fail "构建失败（退出码 $buildExit）。完整日志：$logPath`n        常见原因见 README「常见错误」：缺 MSVC Build Tools（link.exe not found）、缺 icon.ico、WebView2 缺失。"
        }
        # 编译成功、只有复制那一步失败 —— 就是 README 记的 EBUSY
        Write-Warn "pnpm build:dist 退出码 $buildExit，但 Rust 产物已刷新：判定为复制阶段失败（exe 被占用）。"
        $again = Get-EcgProcesses
        if ($again.Count -gt 0) {
            if (-not $StopRunning) {
                $pidsAgain = ($again | ForEach-Object { $_.Id }) -join ', '
                Fail ("仓库根 exe 仍被 edit_config_gui（PID $pidsAgain）占用。关掉它后单独跑 " +
                    '`node scripts/copy-dist.mjs`，或重跑本脚本并加 -StopRunning。')
            }
            foreach ($p in $again) { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue }
            Start-Sleep -Milliseconds 500
        }
        Write-Note '重试复制：node scripts/copy-dist.mjs'
        & node scripts/copy-dist.mjs 2>&1 | Tee-Object -FilePath $logPath -Append
        if ($LASTEXITCODE -ne 0) { Fail "复制产物失败（退出码 $LASTEXITCODE）。日志：$logPath" }
    }

    if (-not $builtFresh) {
        Fail "编译产物没有刷新（$builtExe 的时间戳早于本次构建开始）。可能命中了缓存的空构建，检查日志：$logPath"
    }
    if (-not (Test-Path -LiteralPath $outExe)) {
        Fail "仓库根 exe 不存在：$outExe（copy-dist.mjs 未生效）"
    }

    $hashBuilt = (Get-FileHash -LiteralPath $builtExe -Algorithm SHA256).Hash
    $hashOut = (Get-FileHash -LiteralPath $outExe -Algorithm SHA256).Hash
    if ($hashBuilt -ne $hashOut) {
        Fail ("仓库根 exe 与刚构建的产物不一致（复制没生效或复制到一半）。`n" +
            "        编译产物 $hashBuilt`n        仓库根   $hashOut`n        手动跑 node scripts/copy-dist.mjs 再看。")
    }
    Write-Note '仓库根 exe == 本次编译产物（SHA256 一致）'
}
finally {
    Pop-Location
}

# ---- 9) 汇总 --------------------------------------------------------------
$item = Get-Item -LiteralPath $outExe
$hash = (Get-FileHash -LiteralPath $outExe -Algorithm SHA256).Hash

Write-Host ''
Write-Host '完成：edit_config_gui.exe 已重新生成并覆盖' -ForegroundColor Green
Write-Host ('  产物    : {0}' -f $item.FullName)
Write-Host ('  大小    : {0:N2} MB' -f ($item.Length / 1MB))
Write-Host ('  修改时间: {0}' -f $item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss'))
Write-Host ('  SHA256  : {0}' -f $hash.Substring(0, 16))
Write-Host ('  耗时    : {0:N1} 秒' -f $sw.Elapsed.TotalSeconds)
if ($Backup -and (Test-Path -LiteralPath $outBak)) {
    Write-Host ('  旧版备份: {0}' -f $outBak)
}
Write-Host ('  构建日志: {0}' -f $logPath) -ForegroundColor DarkGray
Write-Host ''
Write-Host '提示：Rust 侧单测不在本脚本范围内，需要时跑 `cd edit_config_gui\src-tauri; cargo test --release`。' -ForegroundColor DarkGray
