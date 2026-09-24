# 批量把 QQ 企鹅的 SWF 动作导成 PNG 帧序列
param(
  [string]$Dl = 'D:\经销商PDCA\clippy-pet\assets-qqpet'
)
$ff = Join-Path $Dl 'ffdec\ffdec.jar'
$A = Join-Path $Dl 'app\src\assets\Action'
$out = Join-Path $Dl 'frames'
New-Item -ItemType Directory -Force -Path $out | Out-Null

$jobs = @(
  @{ n = 'Idle1'; p = 'MM\Adult\peaceful\play\P1.swf' },
  @{ n = 'Idle2'; p = 'MM\Adult\peaceful\play\P10.swf' },
  @{ n = 'Idle3'; p = 'MM\Adult\peaceful\play\P25.swf' },
  @{ n = 'Idle4'; p = 'MM\Adult\peaceful\play\P50.swf' },
  @{ n = 'Idle5'; p = 'MM\Adult\peaceful\play\P75.swf' },
  @{ n = 'Happy'; p = 'MM\Adult\happy\play\P1.swf' },
  @{ n = 'Happy2'; p = 'MM\Adult\happy\play\P5.swf' },
  @{ n = 'Eat'; p = 'MM\Adult\Eat1.swf' },
  @{ n = 'Eat2'; p = 'MM\Adult\Eat2.swf' },
  @{ n = 'Clean'; p = 'MM\Adult\Clean1.swf' },
  @{ n = 'Clean2'; p = 'MM\Adult\Clean2.swf' },
  @{ n = 'Sick'; p = 'MM\Adult\Sick1.swf' },
  @{ n = 'Cure'; p = 'MM\Adult\Cure1.swf' },
  @{ n = 'LevelUp'; p = 'MM\Adult\LevUp.swf' },
  @{ n = 'Speak'; p = 'MM\Adult\peaceful\Speak.swf' },
  @{ n = 'Enter'; p = 'MM\Adult\Enter1.swf' },
  @{ n = 'Exit'; p = 'MM\Adult\Exit1.swf' },
  @{ n = 'Hi1'; p = 'MM\Adult\peaceful\interact\H1.swf' },
  @{ n = 'Hi2'; p = 'MM\Adult\peaceful\interact\BE1.swf' },
  @{ n = 'Hi3'; p = 'MM\Adult\peaceful\interact\LF1.swf' },
  @{ n = 'HappyHi'; p = 'MM\Adult\happy\interact\H1.swf' },
  @{ n = 'KidStand'; p = 'MM\Kid\Stand.swf' },
  @{ n = 'KidEat'; p = 'MM\Kid\Eat1.swf' },
  @{ n = 'KidDirty'; p = 'MM\Kid\Dirty.swf' },
  @{ n = 'KidHungry'; p = 'MM\Kid\Hungry.swf' },
  @{ n = 'EggStand'; p = 'MM\Egg\Stand.swf' },
  @{ n = 'EggAppear'; p = 'MM\Egg\Appear.swf' },
  @{ n = 'GGIdle'; p = 'GG\Adult\peaceful\play\P1.swf' },
  @{ n = 'GGHappy'; p = 'GG\Adult\happy\play\P1.swf' },
  @{ n = 'GGEat'; p = 'GG\Adult\Eat1.swf' }
)

$report = @()
foreach ($j in $jobs) {
  $swf = Join-Path $A $j.p
  $dst = Join-Path $out $j.n
  if (-not (Test-Path $swf)) { $report += [pscustomobject]@{ Name = $j.n; Frames = -1; Note = '源文件不存在' }; continue }
  Remove-Item $dst -Recurse -Force -ErrorAction SilentlyContinue
  New-Item -ItemType Directory -Force -Path $dst | Out-Null
  & java -jar $ff -format frame:png -export frame $dst $swf 2>&1 | Out-Null
  $files = Get-ChildItem $dst -File -ErrorAction SilentlyContinue
  $kb = 0
  if ($files.Count) { $kb = [math]::Round((($files | Measure-Object Length -Sum).Sum) / 1KB) }
  $report += [pscustomobject]@{ Name = $j.n; Frames = $files.Count; KB = $kb; Note = $j.p }
  Write-Output ("  {0,-10} {1,4} 帧  {2,7} KB   {3}" -f $j.n, $files.Count, $kb, $j.p)
}
Write-Output ""
Write-Output ("完成: " + ($report | Where-Object { $_.Frames -gt 1 }).Count + " 个动作, 总 " + (($report | Measure-Object KB -Sum).Sum) + " KB")
Write-Output ("异常(<2 帧): " + (($report | Where-Object { $_.Frames -lt 2 } | ForEach-Object { $_.Name }) -join ', '))
