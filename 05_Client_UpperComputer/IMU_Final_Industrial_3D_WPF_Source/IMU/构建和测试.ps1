$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
# Preflight: catch Windows MAX_PATH errors before .NET reports a missing generated editorconfig.
& (Join-Path $PSScriptRoot 'tools\检查路径长度.ps1') -ProjectRoot $PSScriptRoot
Write-Host "[1/3] Restore" -ForegroundColor Cyan
dotnet restore DynamicInclinometer.slnx
if ($LASTEXITCODE -ne 0) { throw "Restore failed" }
Write-Host "[2/3] Build" -ForegroundColor Cyan
dotnet build DynamicInclinometer.slnx -c Release -p:Platform=x64 --no-restore
if ($LASTEXITCODE -ne 0) { throw "Build failed" }
Write-Host "[3/3] Smoke tests" -ForegroundColor Cyan
dotnet run -c Release --project tests/DynamicInclinometer.SmokeTests -- samples/accel_calibration_device_0002.json
if ($LASTEXITCODE -ne 0) { throw "Smoke tests failed" }
Write-Host "Build + smoke tests complete. This does not replace real hardware verification." -ForegroundColor Green
