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

# F1：按列名定位，不再硬编码列序号。vertu-cli sales +orders 输出列序曾变化，
# 旧实现 $sourceRow[5]/[7]/[8] 取到空值导致每天产出空 customer_summary（455 字节）。
# 与 Python 侧 app/vertu/sales.py::fetch_dealer_sales_orders_sync 保持同一契约。
$columns = @($payload.columns)
if ($columns.Count -eq 0) {
    throw "sales +orders 输出缺少 columns 字段，无法按列名解析"
}
$iName = [Array]::IndexOf($columns, "客户名称")
if ($iName -lt 0) { $iName = [Array]::IndexOf($columns, "客户") }
$iQty  = [Array]::IndexOf($columns, "数量")
$iAmt  = [Array]::IndexOf($columns, "金额")
if ($iName -lt 0 -or $iQty -lt 0 -or $iAmt -lt 0) {
    throw "sales +orders 输出缺少必需列（客户名称/数量/金额）: $($columns -join ',')"
}

$groups = @{}

foreach ($sourceRow in @($payload.rows)) {
    if ($sourceRow -is [System.Array]) {
        $name = [string]$sourceRow[$iName]
        $quantity = [double]$sourceRow[$iQty]
        $amount = [double]$sourceRow[$iAmt]
    } else {
        $name = [string]$sourceRow.($columns[$iName])
        $quantity = [double]$sourceRow.($columns[$iQty])
        $amount = [double]$sourceRow.($columns[$iAmt])
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
