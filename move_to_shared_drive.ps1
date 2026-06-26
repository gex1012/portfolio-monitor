param(
  [string]$Source = "C:\Users\Admin\Documents\New project\portfolio_monitor",
  [string]$DestinationParent = "G:\Shared drives\MarsCap\PnL\Equity Research",
  [switch]$DeleteSourceAfterCopy
)

$ErrorActionPreference = "Stop"

function Get-TreeStats {
  param([string]$Path)
  $files = Get-ChildItem -LiteralPath $Path -Recurse -Force -File
  [pscustomobject]@{
    Count = @($files).Count
    Bytes = ($files | Measure-Object -Property Length -Sum).Sum
  }
}

$sourcePath = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath $DestinationParent)) {
  throw "Destination parent does not exist: $DestinationParent"
}

$destinationParentPath = (Resolve-Path -LiteralPath $DestinationParent).Path
$targetPath = Join-Path $destinationParentPath "portfolio_monitor"

if ($sourcePath -eq $targetPath) {
  throw "Source and target are the same path."
}

if (-not $targetPath.StartsWith($destinationParentPath, [System.StringComparison]::OrdinalIgnoreCase)) {
  throw "Safety check failed: target is outside destination parent."
}

if (Test-Path -LiteralPath $targetPath) {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $targetPath = Join-Path $destinationParentPath "portfolio_monitor-$stamp"
  Write-Host "Target already exists. Using: $targetPath"
}

Write-Host "Copying project..."
Write-Host "From: $sourcePath"
Write-Host "To:   $targetPath"

New-Item -ItemType Directory -Path $targetPath -Force | Out-Null
Copy-Item -Path (Join-Path $sourcePath "*") -Destination $targetPath -Recurse -Force

$sourceStats = Get-TreeStats -Path $sourcePath
$targetStats = Get-TreeStats -Path $targetPath

Write-Host "Source files: $($sourceStats.Count), bytes: $($sourceStats.Bytes)"
Write-Host "Target files: $($targetStats.Count), bytes: $($targetStats.Bytes)"

if ($sourceStats.Count -ne $targetStats.Count -or $sourceStats.Bytes -ne $targetStats.Bytes) {
  throw "Copy verification failed. Source and target stats do not match. Source was not deleted."
}

Write-Host "Copy verified."

if ($DeleteSourceAfterCopy) {
  if (-not $sourcePath.StartsWith("C:\Users\Admin\Documents\New project", [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Safety check failed: refusing to delete source outside the expected workspace."
  }
  Write-Host "Deleting original source..."
  Remove-Item -LiteralPath $sourcePath -Recurse -Force
  Write-Host "Move complete. Project is now at: $targetPath"
} else {
  Write-Host "Copy complete. Original source was kept."
  Write-Host "To turn this into a move, rerun with -DeleteSourceAfterCopy after confirming the target opens correctly."
}
