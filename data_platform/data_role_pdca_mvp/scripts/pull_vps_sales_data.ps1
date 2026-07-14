param(
    [string]$Date = (Get-Date -Format "yyyy-MM-dd"),
    [string]$StartDate = "",
    [string]$Workspace = "",
    [string]$VertuCmd = "vertu-cli"
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

if ([string]::IsNullOrWhiteSpace($Workspace)) {
    $Workspace = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}
if ([string]::IsNullOrWhiteSpace($StartDate)) {
    $StartDate = "$(Get-Date $Date -Format 'yyyy-MM')-01"
}

$OutDir = Join-Path (Split-Path -Parent (Split-Path -Parent $Workspace)) "data_raw"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$suffix = $Date
if ($StartDate -ne $Date) {
    $suffix = "${StartDate}_to_${Date}"
}
$OutFile = Join-Path $OutDir "dealer_sales_month_to_date_$suffix.json"

if (-not (Test-Path -LiteralPath $VertuCmd)) {
    $cmd = Get-Command $VertuCmd -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "vertu-cli not found. Install vertu-cli and authenticate first."
    }
    $VertuCmd = $cmd.Source
}

$raw = & $VertuCmd sales +orders `
    --start-date $StartDate `
    --end-date $Date `
    --dept-l1 "海外渠道" `
    --limit 5000
if ($LASTEXITCODE -ne 0) {
    throw "vertu-cli sales +orders failed with exit code $LASTEXITCODE"
}
$payload = ($raw -join "`n") | ConvertFrom-Json
$groups = @{}

foreach ($sourceRow in @($payload.rows)) {
    # vertu-cli sales +orders shortcut contract:
    # customer name=column 5, quantity=column 7, amount=column 8.
    if ($sourceRow -is [System.Array]) {
        $name = [string]$sourceRow[5]
        $quantity = [double]$sourceRow[7]
        $amount = [double]$sourceRow[8]
    } else {
        $properties = @($sourceRow.PSObject.Properties)
        $name = [string]$properties[5].Value
        $quantity = [double]$properties[7].Value
        $amount = [double]$properties[8].Value
    }
    if ([string]::IsNullOrWhiteSpace($name)) { continue }
    if (-not $groups.ContainsKey($name)) {
        $groups[$name] = [ordered]@{
            partner_name = $name
            performance = 0.0
            quantity = 0
            line_count = 0
        }
    }
    $item = $groups[$name]
    $item.performance += $amount
    $item.quantity += [int]$quantity
    $item.line_count += 1
}

$customerSummary = @($groups.Values | Sort-Object -Property @{Expression = "performance"; Descending = $true})
$result = [ordered]@{
    execution = [ordered]@{
        result = [ordered]@{
            source = "vertu-cli sales +orders"
            start_date = $StartDate
            run_date = $Date
            customer_summary = $customerSummary
        }
    }
}
$result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutFile -Encoding UTF8
Write-Output $OutFile
