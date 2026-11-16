[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$backup = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $backup
$relative = 'src/Dts.Tests/S1/CT27/CT_27_Algorithm.cs'
$source = Join-Path $backup $relative
$target = Join-Path $root $relative
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw 'Backup source missing.' }
Copy-Item -LiteralPath $source -Destination $target -Force
Write-Host 'CT27 V1.0.2 algorithm restored. Rebuild the solution.' -ForegroundColor Green