$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
# Preflight: catch Windows MAX_PATH errors before .NET reports a missing generated editorconfig.
& (Join-Path $PSScriptRoot 'tools\检查路径长度.ps1') -ProjectRoot $PSScriptRoot
if (-not $IsWindows -and $env:OS -ne 'Windows_NT') { throw "WPF 必须在 Windows 上发布" }
dotnet restore DynamicInclinometer.slnx
if ($LASTEXITCODE -ne 0) { throw "还原失败" }
dotnet build DynamicInclinometer.slnx -c Release --no-restore
if ($LASTEXITCODE -ne 0) { throw "编译失败，禁止发布" }
dotnet run --project tests/DynamicInclinometer.SmokeTests -c Release --no-build -- samples/accel_calibration_device_0002.json samples/gyro_calibration_device_0002.json
if ($LASTEXITCODE -ne 0) { throw "算法回归测试未通过，禁止发布" }
$target=Join-Path $PSScriptRoot 'dist/win-x64'
dotnet publish src/DynamicInclinometer.App/DynamicInclinometer.App.csproj -c Release -r win-x64 --self-contained true -p:PublishSingleFile=false -o $target
if ($LASTEXITCODE -ne 0) { throw "发布失败" }
if (!(Test-Path (Join-Path $target '2TD600.dll'))) { throw "缺少 2TD600.dll，禁止交付" }
Write-Host "发布成功：$target" -ForegroundColor Green
Write-Host "尚未经过 IMU 或转台真机闭环试验；现场先校验急停、锁紧、找零路径以及角度方向。" -ForegroundColor Yellow
