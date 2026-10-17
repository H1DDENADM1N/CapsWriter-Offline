<#
.SYNOPSIS
  Trim a full PySide6 / shiboken6 installation down to the minimal runtime set,
  reproducing exactly the trimming that was applied to site-packages_old.

.DESCRIPTION
  What the "old" trim did (verified against site-packages_old, PySide6 6.10.1):
    - Kept ONLY the .pyd/.pyi Python bindings actually used by the app:
        QtCore, QtGui, QtWidgets, QtSvg, QtSvgWidgets, QtUiTools
      (all other Qt* binding modules deleted: Qt3D*, QtBluetooth, QtCharts,
       QtDBus, QtDesigner, QtHelp, QtLocation, QtMultimedia, QtNetwork,
       QtNetworkAuth, QtNfc, QtOpenGL, QtPdf, QtPositioning, QtPrintSupport,
       QtQml, QtQuick*, QtRemoteObjects, QtScxml, QtSensors, QtSerialPort,
       QtSerialBus, QtSql, QtStateMachine, QtTest, QtTextToSpeech,
       QtWebChannel, QtWebEngine*, QtWebSockets, QtWebView, QtXml, ...)
    - Kept ONLY the native Qt DLLs that are the dependency closure of those
      bindings: Qt6Core.dll, Qt6Gui.dll, Qt6Network.dll, Qt6OpenGL.dll,
      Qt6OpenGLWidgets.dll, Qt6Qml.dll, Qt6Svg.dll, Qt6SvgWidgets.dll,
      Qt6UiTools.dll, Qt6Widgets.dll, plus pyside6.abi3.dll
      (every other Qt6*.dll deleted, ~240 saved).
    - Kept the ENTIRE standard plugin catalog (platforms, imageformats,
      sqldrivers, tls, styles, canbus, multimedia, position, sensors,
      texttospeech, designer, sceneparsers, renderers, qmltooling, ...).
      Old's plugin set == new's plugin set minus exactly 4 files:
        qmltooling\qmldbg_quickeventreplay.dll
        vectorimageformats\qlottievectorimage.dll
        webview\qtwebview_webengine.dll
        webview\qtwebview_webview2.dll
    - Deleted all dev/build extras: every *.exe tool (assistant, designer,
      linguist, rcc, uic, lrelease, lupdate, qml* tools, qsb, svgtoqml),
      bundled VC runtime DLLs (msvcp140*, vcruntime140*, vcomp140, concrt140,
      vcamp140, vccorlib140, opengl32sw), FFmpeg DLLs (av*, sw*),
      pyside6qml.abi3.dll, all *.lib, PySide6_*.json, _config.py,
      __feature__.pyi, py.typed, _git_pyside_version.py, and the whole
      doc/, glue/, lib/, qml/, resources/, scripts/, support/,
      translations/, typesystems/, QtAsyncio/ trees.
    - shiboken6: kept only __init__.py + Shiboken.pyd + shiboken6.abi3.dll;
      deleted include/, lib/, _config.py, _git_shiboken_module_version.py,
      py.typed, Shiboken.pyi, all *.lib and all bundled VC runtime DLLs.
    - Never edited __init__.py: PySide6's __init__ computes __all__
      dynamically by globbing the surviving Qt*.pyd files, so deleting files
      (rather than editing code) is the whole mechanism.

  Net effect: PySide6 3851 files/647 MB -> 103 files/66 MB; shiboken6
  69 files/3 MB -> 5 files/0.4 MB (~580 MB freed).

  This script reproduces that EXACT outcome on the new (full) tree by
  deriving the keep-list from the reference (old) tree: every file whose
  relative path exists in the reference is kept, everything else is deleted,
  then empty directories are pruned. It never modifies __init__.py or any
  other file content.

.PARAMETER PySide6
  Target full PySide6 directory to trim.
  Default: <repo root>\site-packages\PySide6
.PARAMETER Shiboken6
  Target full shiboken6 directory to trim.
  Default: <repo root>\site-packages\shiboken6
.PARAMETER Reference
  The trimmed PySide6 directory used as the keep-list source (old).
  Default: <repo root>\site-packages_old\PySide6
.PARAMETER ShibokenRef
  The trimmed shiboken6 directory used as the keep-list source (old).
  Default: <repo root>\site-packages_old\shiboken6
.PARAMETER Apply
  Actually delete files (and prune empty dirs). Without this switch the
  script only reports what would be removed (dry run, no changes).
.PARAMETER BackupDir
  Optional. Only meaningful with -Apply: every removed file is COPIED here
  (preserving its relative path) before deletion, as a safety net.
.PARAMETER Quiet
  Don't print per-file detail; only print summary lines.

.EXAMPLE
  .\dev\trim_pyside6.ps1                          # dry run: report only
  .\dev\trim_pyside6.ps1 -Apply -BackupDir .\removed_pyside6   # real trim + backup

.NOTES
  This script lives in <repo root>\dev\, so the site-packages trees it works on
  sit one level UP from the script directory. Every default path is therefore
  anchored on the repo root (= the parent of the script's own directory), not
  on the script directory itself, and resolves to an absolute path. The script
  can thus be invoked from any current directory.
#>
[CmdletBinding()]
param(
    # This script now lives in <repo root>\dev\, so the trees it trims are one
    # level UP from here: anchor each default on the repo root (the parent of
    # the script's directory) instead of on $PSScriptRoot itself.
    [string]$PySide6 = (Join-Path (Split-Path -Parent $PSScriptRoot) 'site-packages\PySide6'),
    [string]$Shiboken6 = (Join-Path (Split-Path -Parent $PSScriptRoot) 'site-packages\shiboken6'),
    [string]$Reference = (Join-Path (Split-Path -Parent $PSScriptRoot) 'site-packages_old\PySide6'),
    [string]$ShibokenRef = (Join-Path (Split-Path -Parent $PSScriptRoot) 'site-packages_old\shiboken6'),
    [switch]$Apply,
    [string]$BackupDir,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'

function Get-RelFileList {
    param([string]$Root)
    $rootPath = (Resolve-Path $Root).Path
    Get-ChildItem -LiteralPath $rootPath -File -Recurse -Force | ForEach-Object {
        $_.FullName.Substring($rootPath.Length + 1)
    }
}

function Test-TrimTargets {
    foreach ($d in @($PySide6, $Shiboken6, $Reference, $ShibokenRef)) {
        if (-not (Test-Path -LiteralPath $d)) {
            throw "Directory not found: $d"
        }
    }
}

Test-TrimTargets

# ---- 1) Build the keep-list from the reference (old) trees -----------------
$keep = [System.Collections.Generic.HashSet[string]]::new(
    [System.StringComparer]::OrdinalIgnoreCase)
foreach ($f in (Get-RelFileList -Root $Reference)) { [void]$keep.Add($f) }
foreach ($f in (Get-RelFileList -Root $ShibokenRef)) { [void]$keep.Add($f) }
$refCount = $keep.Count

Write-Host "Reference keep-list built: $refCount relative paths (from $Reference / $ShibokenRef)."

# Always protect this entry even if it were somehow absent from the reference.
[void]$keep.Add('__init__.py')

# ---- 2) Classify every file of the target trees ----------------------------
function Invoke-Trim {
    param(
        [string]$TargetRoot,
        [string]$TreeName,
        [System.Collections.Generic.HashSet[string]]$KeepSet,
        [bool]$RealRun,
        [string]$BackupBase,
        [bool]$Silent
    )
    $rootPath = (Resolve-Path $TargetRoot).Path
    $allFiles = @(Get-ChildItem -LiteralPath $rootPath -File -Recurse -Force)
    $kept = @(); $removed = @()
    foreach ($f in $allFiles) {
        $rel = $f.FullName.Substring($rootPath.Length + 1)
        if ($KeepSet.Contains($rel)) { $kept += $f } else { $removed += $f }
    }
    $removedBytes = ($removed | Measure-Object Length -Sum).Sum
    $keptBytes = ($kept   | Measure-Object Length -Sum).Sum

    Write-Host ("[{0}] total={1}  keep={2}  remove={3}  (removed {4:N1} MB, kept {5:N1} MB)" -f `
            $TreeName, $allFiles.Count, $kept.Count, $removed.Count,
        ($removedBytes / 1MB), ($keptBytes / 1MB))

    if (-not $Silent) {
        foreach ($f in ($removed | Sort-Object FullName)) {
            Write-Host ("  - " + $f.FullName.Substring($rootPath.Length + 1))
        }
    }

    if ($RealRun) {
        foreach ($f in $removed) {
            if ($BackupBase) {
                $dst = Join-Path $BackupBase $f.FullName.Substring($rootPath.Length + 1)
                [System.IO.Directory]::CreateDirectory([System.IO.Path]::GetDirectoryName($dst)) | Out-Null
                Copy-Item -LiteralPath $f.FullName -Destination $dst -Force
            }
            Remove-Item -LiteralPath $f.FullName -Force
        }
        # Prune directories that are now empty (bottom-up).
        Get-ChildItem -LiteralPath $rootPath -Directory -Recurse -Force |
        Sort-Object { $_.FullName.Length } -Descending |
        ForEach-Object {
            if (-not (Get-ChildItem -LiteralPath $_.FullName -Force | Select-Object -First 1)) {
                Remove-Item -LiteralPath $_.FullName -Force
            }
        }
    }
    Write-Host ("[{0}] after trim: {1} files, {2:N1} MB" -f `
            $TreeName, $kept.Count, ($keptBytes / 1MB))
    return @{ Tree = $TreeName; Removed = $removed.Count; Kept = $kept.Count; Bytes = $removedBytes }
}

$results = @()
$results += Invoke-Trim -TargetRoot $PySide6  -TreeName 'PySide6'  -KeepSet $keep `
    -RealRun $Apply -BackupBase $BackupDir -Silent $Quiet
$results += Invoke-Trim -TargetRoot $Shiboken6 -TreeName 'shiboken6' -KeepSet $keep `
    -RealRun $Apply -BackupBase $BackupDir -Silent $Quiet

$totBytes = ($results | Measure-Object Bytes -Sum).Sum
Write-Host ""
if ($Apply) {
    Write-Host "DONE: trimmed $( ($results | Measure-Object Removed -Sum).Sum ) files," `
        "freed $([math]::Round($totBytes/1MB,1)) MB. Empty directories pruned."
    if ($BackupDir) {
        Write-Host "Removed files were copied to: $BackupDir"
    }
}
else {
    Write-Host "DRY RUN (no changes made): would remove $( ($results | Measure-Object Removed -Sum).Sum ) files," `
        "freeing $([math]::Round($totBytes/1MB,1)) MB."
    Write-Host "Re-run with -Apply to actually trim. Add -BackupDir <dir> to keep a copy of removed files."
}
