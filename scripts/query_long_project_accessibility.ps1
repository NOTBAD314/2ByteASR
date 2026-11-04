param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$auditRoot = [IO.Path]::GetFullPath($OutputDirectory)
$tracePath = Join-Path $auditRoot 'uia-queries.jsonl'
$deadline = [DateTime]::UtcNow.AddMinutes(10)
$iteration = 0
while ([DateTime]::UtcNow -lt $deadline -and -not (Test-Path -LiteralPath (Join-Path $auditRoot 'resources-stop'))) {
    try {
        $record = Get-Content -LiteralPath (Join-Path $auditRoot 'result.json') -Raw | ConvertFrom-Json
        if ($record.phase -notin @('thirty-mixed-operations','rapid-latest-target')) {
            Start-Sleep -Milliseconds 200
            continue
        }
        $timer = [Diagnostics.Stopwatch]::StartNew()
        $window = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr][long]$record.hwnd)
        $gridCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::DataGrid)
        $tableCondition = New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Table)
        $condition = New-Object System.Windows.Automation.OrCondition($gridCondition,$tableCondition)
        $table = $window.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$condition)
        if ($null -eq $table) { throw 'No accessible table was found in this owned test window.' }
        $grid = $table.GetCurrentPattern([System.Windows.Automation.GridPattern]::Pattern)
        $rows = $grid.Current.RowCount
        $columns = $grid.Current.ColumnCount
        $count = 0
        if ($rows -gt 0 -and $columns -gt 0) {
            foreach ($row in @(0,[Math]::Min(3041,$rows-1),$rows-1)) {
                $cell = $grid.GetItem($row,[Math]::Min(3,$columns-1))
                $enabled = $cell.Current.IsEnabled
                $offscreen = $cell.Current.IsOffscreen
                $rectangle = $cell.Current.BoundingRectangle
                $count++
            }
        }
        $entry = @{iteration=$iteration;pid=$record.pid;rows=$rows;columns=$columns;cells=$count;ms=$timer.Elapsed.TotalMilliseconds;passed=$true}
    } catch {
        $entry = @{iteration=$iteration;passed=$false;error=$_.Exception.Message}
    }
    $entry | ConvertTo-Json -Compress | Add-Content -LiteralPath $tracePath -Encoding UTF8
    $iteration++
    Start-Sleep -Milliseconds 150
}
