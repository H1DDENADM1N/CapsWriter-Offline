# backup.ps1 —— 把 archive_list.txt 里的内容打进 7z 备份包
#
# 依赖:
#   7-Zip        C:\Program Files\7-Zip\7z.exe
#   Everything   dev\tools\es.exe（官方 ES 命令行工具），只用于压缩前检索 __pycache__
#                ES 缺失、报错或 Everything 未运行时，自动回退到 Get-ChildItem 原生枚举
param(
    [string]$ArchiveName = "backup.7z",
    [string]$EsPath = "dev\tools\es.exe",
    [switch]$SkipPycacheCleanup
)

# 让控制台正确显示 7-Zip 的中文错误信息
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

$sevenZip = "C:\Program Files\7-Zip\7z.exe"
$listFile = "dev\archive_list.txt"

# 脚本位于 dev\ 下，项目根目录是它的上一级
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $projectRoot) { $projectRoot = (Get-Location).Path }

# 1. 检查 7z 是否可用
if (-not (Get-Command $sevenZip -ErrorAction SilentlyContinue)) {
    Write-Error "未找到 7z，请安装 7-Zip 或将其加入 PATH。"
    exit 1
}

# 2. 检查列表文件是否存在
if (-not (Test-Path $listFile)) {
    Write-Error "未找到文件列表：$listFile"
    exit 1
}

$listFileFull = (Resolve-Path $listFile).Path

# 3. 读取列表，过滤空行和注释
$rawEntries = Get-Content $listFileFull -Encoding UTF8 |
    ForEach-Object { $_.Trim() } |
    Where-Object { $_ -ne "" -and -not $_.StartsWith("#") }

Write-Host "列表文件: $listFileFull"
Write-Host "原始条目数: $($rawEntries.Count)"

if ($rawEntries.Count -eq 0) {
    Write-Error "$listFile 中没有有效的文件条目。"
    exit 1
}

# 4. 把每个条目解析为绝对路径
#    相对路径以脚本所在目录（项目根目录）为基准
$files = @()
foreach ($entry in $rawEntries) {
    $resolved = Resolve-Path -Path $entry -ErrorAction SilentlyContinue
    if ($resolved) {
        $files += $resolved.Path
    } else {
        # 相对脚本目录再试一次
        $candidate = Join-Path $PSScriptRoot $entry
        $resolved2 = Resolve-Path -Path $candidate -ErrorAction SilentlyContinue
        if ($resolved2) {
            $files += $resolved2.Path
        } else {
            Write-Warning "找不到条目，已跳过: $entry"
        }
    }
}

Write-Host "有效文件数: $($files.Count)"

if ($files.Count -eq 0) {
    Write-Error "列表中的所有条目都无法解析为实际文件，请检查 archive_list.txt 中的路径。"
    exit 1
}

# 5. 压缩前清理 __pycache__
#    优先用 Everything 的官方命令行工具 ES 检索：直接查 Everything 索引，速度极快；
#    只有 ES 不可用或 Everything 未运行时才回退到 Get-ChildItem 递归枚举。
#    检索范围严格限定在「列表里解析为目录」的条目内，不做全盘清理。
if ($SkipPycacheCleanup) {
    Write-Host "__pycache__ 清理: 已用 -SkipPycacheCleanup 跳过。"
} else {
    # 5.1 找出列表里的目录条目
    $dirTargets = @($files | Where-Object { Test-Path -LiteralPath $_ -PathType Container })
    Write-Host "__pycache__ 检索范围: $($dirTargets.Count) 个目录"

    # 5.2 定位 ES：$EsPath 相对项目根目录，其次当前目录，最后 PATH
    $es = $null
    foreach ($candidate in @($EsPath, (Join-Path $projectRoot $EsPath), (Join-Path (Get-Location) $EsPath))) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $es = (Resolve-Path -LiteralPath $candidate).Path
            break
        }
    }
    if (-not $es) {
        $esCmd = Get-Command "es.exe" -ErrorAction SilentlyContinue
        if ($esCmd) { $es = $esCmd.Source }
    }

    $found = New-Object System.Collections.Generic.List[string]
    $usedEverything = $false

    # 5.3 用 ES 逐个目录检索（ES 默认输出为完整路径一行一条，目录带尾随反斜杠）
    if ($es) {
        Write-Host "Everything 命令行: $es"
        $esOk = $true
        foreach ($dir in $dirTargets) {
            $lines = & $es -path $dir /ad -timeout 10000 "__pycache__" 2>$null
            if ($LASTEXITCODE -ne 0) {
                # 退出码 8 = Everything 未运行
                Write-Warning "ES 检索失败（退出码 $LASTEXITCODE），回退原生枚举。"
                $esOk = $false
                break
            }
            foreach ($line in $lines) {
                $p = "$line".Trim().TrimEnd('\')
                # 只接受名字恰好为 __pycache__、且确实位于该目录下的结果
                if ($p -and (Split-Path -Leaf $p) -eq "__pycache__" -and $p.StartsWith($dir, [System.StringComparison]::OrdinalIgnoreCase)) {
                    $found.Add($p)
                }
            }
        }
        if ($esOk) { $usedEverything = $true }
    }

    # 5.4 回退：原生递归枚举
    if (-not $usedEverything) {
        $found.Clear()
        if (-not $es) {
            Write-Warning "未找到 Everything 命令行工具 es.exe（$EsPath），改用 PowerShell 原生枚举。"
        }
        foreach ($dir in $dirTargets) {
            Get-ChildItem -LiteralPath $dir -Directory -Recurse -Force -Filter "__pycache__" -ErrorAction SilentlyContinue |
                ForEach-Object { $found.Add($_.FullName) }
        }
    }

    # 5.5 去重。若 __pycache__ 本身就在备份列表里，则不能删，否则 7z 会找不到条目
    $targets = @($found | Select-Object -Unique | Where-Object { $files -notcontains $_ })

    if ($targets.Count -eq 0) {
        Write-Host "__pycache__ 清理: 没有需要清理的目录。"
    } else {
        $fileCount = 0
        foreach ($t in $targets) {
            $fileCount += @(Get-ChildItem -LiteralPath $t -Recurse -File -Force -ErrorAction SilentlyContinue).Count
        }
        $source = if ($usedEverything) { "Everything" } else { "原生枚举" }
        Write-Host "__pycache__ 清理: 发现 $($targets.Count) 个目录 / $fileCount 个文件（来源: $source），开始删除..."

        # 由深到浅删除，避免父目录先删掉后子目录重复处理
        $removedDirs = 0
        foreach ($t in ($targets | Sort-Object Length -Descending)) {
            Remove-Item -LiteralPath $t -Recurse -Force -ErrorAction SilentlyContinue
            if (-not (Test-Path -LiteralPath $t)) { $removedDirs++ }
        }
        Write-Host "__pycache__ 清理: 已删除 $removedDirs 个目录。"
    }
}

# 6. 组装 7-Zip 参数，文件以绝对路径逐个传入
$arguments = @(
    "a", "-t7z", "-mx=9", "-m0=LZMA2",
    "-md=64m", "-mfb=64",
    # -mcu 不是有效的 7-Zip 参数，会让 7z 以 "System ERROR: 参数错误" 失败，切勿加回
    "-mmt=on", "-sccUTF-8",
    $ArchiveName
) + $files

Write-Host "执行: 7z $($arguments -join ' ')"
& $sevenZip @arguments

# 7. 检查 7z 退出码
if ($LASTEXITCODE -ne 0) {
    Write-Error "7-Zip 执行失败，退出码: $LASTEXITCODE"
    exit $LASTEXITCODE
}

Write-Host "压缩完成: $ArchiveName"
