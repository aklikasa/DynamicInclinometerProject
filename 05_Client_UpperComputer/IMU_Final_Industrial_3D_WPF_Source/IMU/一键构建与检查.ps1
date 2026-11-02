# 在安装 .NET 10 SDK 和 WPF 桌面组件的 Windows / PowerShell 中运行
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
# Preflight: catch Windows MAX_PATH errors before .NET reports a missing generated editorconfig.
& (Join-Path $PSScriptRoot 'tools\检查路径长度.ps1') -ProjectRoot $PSScriptRoot
$log = Join-Path $PSScriptRoot 'build_validation_log.txt'
"WPF build started: $(Get-Date -Format o)" | Set-Content -Path $log -Encoding UTF8
try {
    $cmd = Get-Command dotnet -ErrorAction Stop
    "dotnet: $($cmd.Source)" | Tee-Object -FilePath $log -Append
    dotnet --info 2>&1 | Out-File -FilePath $log -Append -Encoding UTF8
    dotnet restore .\DynamicInclinometer.slnx 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) { throw "dotnet restore failed ($LASTEXITCODE)" }
    dotnet build .\DynamicInclinometer.slnx -c Release --no-restore 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) { throw "dotnet build failed ($LASTEXITCODE)" }
    dotnet run -c Release --project .\tests\DynamicInclinometer.SmokeTests\DynamicInclinometer.SmokeTests.csproj -- .\samples\accel_calibration_device_0002.json .\samples\gyro_calibration_device_0002.json 2>&1 | Tee-Object -FilePath $log -Append
    if ($LASTEXITCODE -ne 0) { throw "Smoke tests failed ($LASTEXITCODE)" }
    Write-Host '编译和基础测试完成（不代表转台实机安全验收）' -ForegroundColor Green
} catch {
    $_ | Out-String | Tee-Object -FilePath $log -Append
    Write-Host "检查失败。完整错误日志：$log" -ForegroundColor Red
    throw
}
