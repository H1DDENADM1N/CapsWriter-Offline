<#
.SYNOPSIS
    递归检查文件夹下所有 .srt 是否含中文，按行去重输出中文内容及行号，并写入结果文件。

.PARAMETER FolderPath
    包含 SRT 字幕的文件夹路径（递归扫描 .srt）。

.PARAMETER Context
    可选。输出该行中文匹配前后各 N 个字符的上下文，默认 0 只输出中文内容。

.PARAMETER Encoding
    编码方式，默认 Auto（BOM 检测；无 BOM 先严格 UTF-8，失败回退系统 ANSI/GBK）。

.PARAMETER OutFile
    结果输出文件路径。默认：脚本所在目录下的 "字幕检查结果.txt"。

.EXAMPLE
    .\Check-SrtChinese.ps1 "D:\subs"

.EXAMPLE
    .\Check-SrtChinese.ps1 "D:\subs" -Context 5 -OutFile "D:\report.txt"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [ValidateNotNullOrEmpty()]
    [string]$FolderPath,

    [int]$Context = 0,

    [ValidateSet('Auto', 'UTF8', 'Default', 'Unicode', 'BigEndianUnicode')]
    [string]$Encoding = 'Auto',

    [string]$OutFile = (Join-Path $PSScriptRoot '字幕检查结果.txt')
)

if (-not (Test-Path -LiteralPath $FolderPath -PathType Container)) {
    Write-Error "文件夹不存在: $FolderPath"
    exit 2
}

function Get-Text {
    param([string]$File, [string]$Enc)
    $bytes = [System.IO.File]::ReadAllBytes($File)
    switch ($Enc) {
        'UTF8'             { return [System.Text.Encoding]::UTF8.GetString($bytes) }
        'Default'          { return [System.Text.Encoding]::Default.GetString($bytes) }
        'Unicode'          { return [System.Text.Encoding]::Unicode.GetString($bytes) }
        'BigEndianUnicode' { return [System.Text.Encoding]::BigEndianUnicode.GetString($bytes) }
        'Auto' {
            if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
                return [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
            }
            if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFF -and $bytes[1] -eq 0xFE) {
                return [System.Text.Encoding]::Unicode.GetString($bytes, 2, $bytes.Length - 2)
            }
            if ($bytes.Length -ge 2 -and $bytes[0] -eq 0xFE -and $bytes[1] -eq 0xFF) {
                return [System.Text.Encoding]::BigEndianUnicode.GetString($bytes, 2, $bytes.Length - 2)
            }
            try {
                $strict = New-Object System.Text.UTF8Encoding($false, $true)
                return $strict.GetString($bytes)
            }
            catch {
                return [System.Text.Encoding]::Default.GetString($bytes)
            }
        }
    }
}

$pattern = '[\u4E00-\u9FFF\u3400-\u4DBF\uF900-\uFAFF]+'

$files = @(Get-ChildItem -LiteralPath $FolderPath -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension -ieq '.srt' } |
    Sort-Object FullName)

# 收集所有输出行，最后统一写入文件
$outputLines = New-Object System.Collections.Generic.List[string]

function Write-Both {
    param([string]$Text, [string]$Color = 'White')
    $script:outputLines.Add($Text)
    if ($Color) { Write-Host $Text -ForegroundColor $Color } else { Write-Host $Text }
}

if ($files.Count -eq 0) {
    Write-Both ("未找到 .srt 文件: {0}" -f $FolderPath) 'Yellow'
    $outputLines | Out-File -FilePath $OutFile -Encoding UTF8
    exit 1
}

$any = $false

foreach ($f in $files) {
    $content = Get-Text -File $f.FullName -Enc $Encoding
    if ([string]::IsNullOrEmpty($content)) { continue }

    $matches = [regex]::Matches($content, $pattern)
    if ($matches.Count -eq 0) { continue }

    $any = $true

    # 每行起始偏移表，供二分查找行号
    $lineStarts = New-Object System.Collections.Generic.List[int]
    $lineStarts.Add(0)
    for ($i = 0; $i -lt $content.Length; $i++) {
        if ($content[$i] -eq "`n") { $lineStarts.Add($i + 1) }
    }

    # 按行号聚合：普通 Hashtable
    $byLine = @{}

    foreach ($m in $matches) {
        # 偏移 -> 行号
        $lo = 0; $hi = $lineStarts.Count - 1
        while ($lo -lt $hi) {
            $mid = [int](($lo + $hi + 1) / 2)
            if ($lineStarts[$mid] -le $m.Index) { $lo = $mid } else { $hi = $mid - 1 }
        }
        $line = $lo + 1

        if ($byLine.ContainsKey($line)) {
            $byLine[$line].Text += " " + $m.Value
        }
        else {
            $byLine[$line] = [pscustomobject]@{
                Line     = $line
                FirstIdx = $m.Index
                Text     = $m.Value
            }
        }
    }

    Write-Both "" 'White'
    # 只输出文件名，不输出路径
    Write-Both ("=== {0} ===" -f $f.Name) 'Cyan'

    # 按行号升序输出
    foreach ($entry in ($byLine.Values | Sort-Object Line)) {
        if ($Context -gt 0) {
            $s = [Math]::Max(0, $entry.FirstIdx - $Context)
            $e = [Math]::Min($content.Length - 1, $entry.FirstIdx + $entry.Text.Length - 1 + $Context)
            $display = $content.Substring($s, $e - $s + 1) -replace "`r?`n", '\n'
        }
        else {
            $display = $entry.Text
        }

        Write-Both ("行 {0,-5} {1}" -f $entry.Line, $display) 'White'
    }
}

# 统一写入文件
$outputLines | Out-File -FilePath $OutFile -Encoding UTF8
Write-Host ""
Write-Host ("结果已写入: {0}" -f $OutFile) -ForegroundColor Green

if ($any) { exit 0 } else { exit 1 }