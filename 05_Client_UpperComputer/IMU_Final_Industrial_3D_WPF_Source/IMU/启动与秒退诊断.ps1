$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$log = Join-Path $env:LOCALAPPDATA 'DynamicInclinometerLab\errors.log'
Write-Host '=== 动态倾角仪：启动/异常诊断 ===' -ForegroundColor Cyan
Write-Host '诊断日志:' $log
Write-Host '编译 WPF 程序 ...' -ForegroundColor Cyan
& dotnet build 'src\DynamicInclinometer.App\DynamicInclinometer.App.csproj' -c Release -r win-x64
if ($LASTEXITCODE -ne 0) { Write-Error '编译失败。请将 Visual Studio 的错误列表或编译日志发给研发人员。'; exit $LASTEXITCODE }
Write-Host '正在启动程序。若窗口意外关闭，请查看后续打印的退出码和日志。' -ForegroundColor Cyan
& dotnet run --no-build -c Release -r win-x64 --project 'src\DynamicInclinometer.App\DynamicInclinometer.App.csproj'
$exitCode = $LASTEXITCODE
Write-Host ('程序退出码: ' + $exitCode)
if (Test-Path $log) {
    Write-Host '--- 最近 80 行运行日志 ---' -ForegroundColor Yellow
    Get-Content -LiteralPath $log -Tail 80
} else {
    Write-Warning '没有生成托管故障日志。若程序秒退，请同时查看 Windows 事件查看器 -> Windows 日志 -> 应用程序。'
}
if ($exitCode -ne 0) { exit $exitCode }
