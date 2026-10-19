# archive.ps1 —— 按 archive_list.txt 打包发布用的 7z 压缩包
#
# 列表里只放「运行时需要的东西」：可执行的 exe、PyStand 要跑的 .py、runtime/、
# 模型之外的必需数据（keywords.txt、hot-*.txt、configs/）等。
# 源码树、设计稿、构建中间产物一律不进包——edit_config_gui 的源码、dev/、
# docs/superpowers/ 都不该出现在这里；发布包里多一份源码只会增大体积并泄露开发内容。
#
# 合规文件是例外：LICENSES/（第三方许可原文）与 docs/开源许可.md（清单与再发布
# 检查清单）是再分发时必须随包附带的文件，readme.md 的「📜 开源许可」章节也指向它们，
# 所以它们显式列在 archive_list.txt 里，不要因为「在 docs/ 下」就删掉。
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

# 4. 把每个条目解析成绝对路径（用于校验与 __pycache__ 检索），
#    同时算出「相对项目根目录」的写法——传给 7z 的必须是后者。
#
#    原因：7z 对「绝对路径的单文件」会丢掉中间目录、直接平铺到包根，
#    对目录则保留目录名。也就是说 `docs\开源许可.md` 若以绝对路径传入，
#    在包里会变成根目录下的 `开源许可.md`，readme.md 里的相对链接就断了。
#    传相对路径并让 7z 以项目根为工作目录，包内层级才与仓库一致。
#
#    条目基准目录顺序：项目根 → 当前目录 → 脚本所在目录（dev\）
$files = @()
$resolvedPairs = @()
foreach ($entry in $rawEntries) {
    $abs = $null
    foreach ($base in @($projectRoot, (Get-Location).Path, $PSScriptRoot)) {
        $candidate = if ([System.IO.Path]::IsPathRooted($entry)) { $entry } else { Join-Path $base $entry }
        $r = Resolve-Path -LiteralPath $candidate -ErrorAction SilentlyContinue
        if ($r) { $abs = $r.Path; break }
    }
    if (-not $abs) {
        Write-Warning "找不到条目，已跳过: $entry"
        continue
    }

    $files += $abs

    # 项目根下的条目转成相对路径；根外的条目只能传绝对路径（7z 会平铺，给出告警）
    if ($abs.StartsWith($projectRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        $rel = $abs.Substring($projectRoot.Length).TrimStart('\')
    } else {
        $rel = $abs
        Write-Warning "条目不在项目根目录下，7z 会将其平铺到包根: $entry"
    }
    $resolvedPairs += [pscustomobject]@{ Abs = $abs; Rel = $rel }
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

# 6. 组装 7-Zip 参数
#    条目一律用「相对项目根目录」的写法，并把项目根设为工作目录，
#    这样包内层级与仓库一致（详见第 4 步注释：绝对路径的单文件会被平铺到包根）。
#    压缩包本身的路径也要先转成绝对路径，否则工作目录切到项目根后就找不到了。
$archiveAbs = if ([System.IO.Path]::IsPathRooted($ArchiveName)) { $ArchiveName } else { Join-Path (Get-Location).Path $ArchiveName }

$arguments = @(
    "a", "-t7z", "-mx=9", "-m0=LZMA2",
    "-md=64m", "-mfb=64",
    # -mcu 不是有效的 7-Zip 参数，会让 7z 以 "System ERROR: 参数错误" 失败，切勿加回
    "-mmt=on", "-sccUTF-8",
    $archiveAbs
) + ($resolvedPairs | ForEach-Object { $_.Rel })

Write-Host "执行: 7z $($arguments -join ' ')"
Push-Location $projectRoot
try {
    & $sevenZip @arguments
    $sevenZipExit = $LASTEXITCODE
} finally {
    Pop-Location
}

# 7. 检查 7z 退出码
if ($sevenZipExit -ne 0) {
    Write-Error "7-Zip 执行失败，退出码: $sevenZipExit"
    exit $sevenZipExit
}

Write-Host "压缩完成: $ArchiveName"

# 8. 计算 SHA-256 校验值：打印成可直接粘贴到发布说明的格式，并复制到剪贴板
#    格式:
#      **程序** <压缩文件名>
#      > #️⃣ SHA-256 `<SHA-256值>`
#    7z 生成的是工作目录下的相对路径，这里统一解析成绝对路径再取文件名
#    -ArchiveName 不带扩展名时 7z 会自动补 .7z，所以先按原名找，再按 <名>.7z 找一次
$archivePath = $archiveAbs
foreach ($candidate in @($archiveAbs, "$archiveAbs.7z")) {
    if (Test-Path -LiteralPath $candidate -PathType Leaf) {
        $archivePath = (Resolve-Path -LiteralPath $candidate).Path
        break
    }
}

if (Test-Path -LiteralPath $archivePath -PathType Leaf) {
    $archiveFile = Split-Path -Leaf $archivePath
    # Get-FileHash 输出本来就是大写十六进制，ToUpperInvariant 只是把格式钉死
    $sha256 = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToUpperInvariant()

    $shaBlock = "**程序** {0}`n> #️⃣ SHA-256 ``{1}``" -f $archiveFile, $sha256

    Write-Host ""
    Write-Host $shaBlock

    # 剪贴板不可用时（例如无交互会话）只告警，不影响打包结果
    try {
        Set-Clipboard -Value $shaBlock
        Write-Host "SHA-256 已复制到剪贴板。"
    } catch {
        Write-Warning "复制 SHA-256 到剪贴板失败: $($_.Exception.Message)"
    }
} else {
    Write-Warning "压缩包不存在，跳过 SHA-256 计算: $ArchiveName"
}
