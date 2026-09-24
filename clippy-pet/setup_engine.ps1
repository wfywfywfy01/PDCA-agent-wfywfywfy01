# 把 Clippy 引擎与素材铺到本目录（幂等，只复制文件）
# 用法: powershell -NoProfile -ExecutionPolicy Bypass -File setup_engine.ps1
[CmdletBinding()]
param(
    [string]$Here = '',
    [string]$Source = 'D:\经销商PDCA\pdca-workbench\app\vps_pet_pack\clippy_pet\engine'
)

$ErrorActionPreference = 'Continue'
if (-not $Here) { $Here = Split-Path -Parent $MyInvocation.MyCommand.Path }

# 如果目标已经铺好，直接跳过（这一步大多数时候不需要再跑）
$need = @(
    'engine\index.mjs',
    'engine\agents\clippy\agent.mjs',
    'engine\agents\clippy\map.mjs',
    'engine\agents\clippy\sounds-mp3.mjs'
)
$missing = @()
foreach ($r in $need) { if (-not (Test-Path (Join-Path $Here $r))) { $missing += $r } }
if ($missing.Count -eq 0) {
    Write-Host "引擎素材已就绪，无需铺设：" -ForegroundColor Green
    Get-ChildItem (Join-Path $Here 'engine') -Recurse -File |
        Select-Object @{n = 'rel'; e = { $_.FullName.Substring($Here.Length) } }, Length |
        Format-Table -AutoSize | Out-String | Write-Host
    exit 0
}

Write-Host "缺少 $($missing.Count) 个文件，准备从素材源复制："
$missing | ForEach-Object { Write-Host "  - $_" }

if (-not (Test-Path $Source)) { Write-Host "找不到素材源: $Source" -ForegroundColor Red; exit 1 }

$pairs = @(
    @{ from = 'index.mjs'; to = 'engine\index.mjs' },
    @{ from = 'chunk.mjs'; to = 'engine\chunk.mjs' },
    @{ from = 'agents\clippy\index.mjs'; to = 'engine\agents\clippy\index.mjs' },
    @{ from = 'agents\clippy\agent.mjs'; to = 'engine\agents\clippy\agent.mjs' },
    @{ from = 'agents\clippy\map.mjs'; to = 'engine\agents\clippy\map.mjs' },
    @{ from = 'agents\clippy\sounds-mp3.mjs'; to = 'engine\agents\clippy\sounds-mp3.mjs' }
)

$ok = 0
foreach ($p in $pairs) {
    $src = Join-Path $Source $p.from
    $dst = Join-Path $Here $p.to
    $dir = Split-Path -Parent $dst
    if (-not (Test-Path $src)) { Write-Host "[x] 缺源文件 $src" -ForegroundColor Red; continue }
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    Copy-Item $src $dst -Force
    $len = (Get-Item $dst).Length
    Write-Host ("[ok] {0,-42} {1,10:N0} bytes" -f $p.to, $len) -ForegroundColor Green
    $ok++
}

Write-Host ""
if ($ok -eq $pairs.Count) {
    Write-Host "素材齐了（$ok/$($pairs.Count)）。下一步: 双击 自检.cmd" -ForegroundColor Green
    exit 0
}
Write-Host "只铺了 $ok / $($pairs.Count)，请检查素材源" -ForegroundColor Yellow
exit 2
