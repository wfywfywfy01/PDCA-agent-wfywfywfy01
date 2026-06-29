param(
    [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
    [string]$StartDate = "",
    [string]$Workspace = "",
    [string]$VertuCmd = "C:\Users\frank\AppData\Roaming\npm\vertu.cmd"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if ([string]::IsNullOrWhiteSpace($Workspace)) {
    $Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

$QueryFile = Join-Path $Workspace "system_queries\pull_dealer_sales_odoo_sale.py"
$OutDir = Join-Path (Split-Path -Parent (Split-Path -Parent $Workspace)) "data_raw"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$suffix = $Date
if (-not [string]::IsNullOrWhiteSpace($StartDate) -and $StartDate -ne $Date) {
    $suffix = "${StartDate}_to_${Date}"
}
$OutFile = Join-Path $OutDir "dealer_sales_month_to_date_$suffix.json"
$ParamsFile = Join-Path $OutDir "dealer_sales_month_to_date_$suffix.params.json"

$paramsPayload = @{ run_date = $Date }
if (-not [string]::IsNullOrWhiteSpace($StartDate)) {
    $paramsPayload.start_date = $StartDate
}
$paramsJson = $paramsPayload | ConvertTo-Json -Compress
$paramsJson | Set-Content -LiteralPath $ParamsFile -Encoding UTF8

if (-not (Test-Path -LiteralPath $VertuCmd)) {
    $cmd = Get-Command vertu -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "vertu CLI not found. Install/login vps-cli first."
    }
    $VertuCmd = $cmd.Source
}

$result = & $VertuCmd odoo data sandbox --code-file $QueryFile --params-file $ParamsFile
$resultText = ($result -join "`n")
$resultText | Set-Content -LiteralPath $OutFile -Encoding UTF8
Write-Output $OutFile
