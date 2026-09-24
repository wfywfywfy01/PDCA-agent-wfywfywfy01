# 分块拉取 app.asar 的 deflate 数据流（每块 8MB，失败重试 6 次）
$dl = 'D:\经销商PDCA\clippy-pet\assets-qqpet'
$chunkDir = Join-Path $dl 'chunks'
$url = 'https://github.com/xuemian168/qqpet_automation/releases/download/v1.6.1-rc.1/QQ.-1.6.1-rc.1-arm64-mac.zip'
$START = 90294404
$END = 266702998
$TOTAL = $END - $START + 1
$CHUNK = 8388608

New-Item -ItemType Directory -Force -Path $chunkDir | Out-Null

$sw = [Diagnostics.Stopwatch]::StartNew()
$pos = $START
$idx = 0
$done = 0
while ($pos -le $END) {
  $idx++
  $to = [Math]::Min($pos + $CHUNK - 1, $END)
  $want = $to - $pos + 1
  $out = Join-Path $chunkDir ('chunk-{0:d5}.bin' -f $idx)

  $have = 0
  if (Test-Path $out) { $have = (Get-Item $out).Length }
  if ($have -eq $want) {
    $done += $have
    $pos = $to + 1
    continue
  }

  $ok = $false
  for ($try = 1; $try -le 6 -and -not $ok; $try++) {
    Remove-Item $out -Force -ErrorAction SilentlyContinue
    & curl.exe -sL --fail --max-time 180 --connect-timeout 20 -r "$pos-$to" -o $out $url 2>$null
    if ((Test-Path $out) -and ((Get-Item $out).Length -eq $want)) { $ok = $true }
    else { Start-Sleep -Seconds (3 * $try) }
  }
  if (-not $ok) {
    Write-Output ("FAIL 块 {0} ({1}-{2}) 重试 6 次都没成功，已完成 {3:N1} MB" -f $idx, $pos, $to, ($done / 1MB))
    exit 1
  }
  $done += $want
  $pos = $to + 1
  if ($idx % 4 -eq 0 -or $pos -gt $END) {
    $kbs = ($done / 1KB) / [Math]::Max(1, $sw.Elapsed.TotalSeconds)
    Write-Output ("进度 {0:N1}/{1:N1} MB  {2:N0} KB/s  已用 {3:N0}s" -f ($done / 1MB), ($TOTAL / 1MB), $kbs, $sw.Elapsed.TotalSeconds)
  }
}
$sw.Stop()
Write-Output ("下载完成 {0:N1} MB / {1:N0}s" -f ($TOTAL / 1MB), $sw.Elapsed.TotalSeconds)
