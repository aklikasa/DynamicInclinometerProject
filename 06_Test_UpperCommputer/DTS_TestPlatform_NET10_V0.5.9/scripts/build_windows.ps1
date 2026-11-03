param(
    [ValidateSet('Debug','Release')][string]$Configuration = 'Debug',
    [switch]$Run
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $projectRoot
New-Item -ItemType Directory -Force -Path 'build_logs' | Out-Null
$log = Join-Path $projectRoot ('build_logs\last_build_' + $Configuration.ToLower() + '.log')
$exe = Join-Path $projectRoot ('src\Dts.Wpf\bin\' + $Configuration + '\net10.0-windows\Dts.TestPlatform.exe')

Write-Host '======================================================'
Write-Host ' 动态倾角仪研发平台 V0.5.7 — Windows 构建/EXE 诊断'
Write-Host '======================================================'
Write-Host ('工程：' + $projectRoot)
Write-Host ('日志：' + $log)
Write-Host ('预期 EXE：' + $exe)

$dotnet = Get-Command dotnet -ErrorAction SilentlyContinue
if (-not $dotnet) { throw '未发现 dotnet。请安装 .NET 10 SDK（不是仅安装运行时），在 PowerShell 中检查 dotnet --list-sdks。' }
$sdks = (& dotnet --list-sdks) -join "`n"
Write-Host ('已安装 SDK：' + $sdks)
if ($sdks -notmatch '(?m)^10\.') { throw '未发现 .NET 10 SDK。请安装支持 net10.0-windows 的 .NET 10 SDK 与桌面开发工作负载。' }

if (Get-Command python -ErrorAction SilentlyContinue) {
    Write-Host '[预检] Python 静态检查（非软件运行必需）'
    & python scripts/check_sources.py
    if ($LASTEXITCODE -ne 0) { throw 'XAML/测试模块静态预检失败；请查看上一条具体错误。' }
}
Write-Host '[1/3] 还原依赖（需要首次访问 NuGet 或配置本地包缓存）'
& dotnet restore src/Dts.Wpf/Dts.Wpf.csproj -p:UseAppHost=true 2>&1 | Tee-Object -FilePath $log
if ($LASTEXITCODE -ne 0) { throw ('还原失败。打开 ' + $log + ' 查找第一条 NU**** 错误。') }

Write-Host '[2/3] 清晰编译输出：优先显示首条真正错误'
& dotnet build src/Dts.Wpf/Dts.Wpf.csproj -c $Configuration --no-restore --no-incremental -p:UseAppHost=true -v:minimal 2>&1 | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) { throw ('编译失败，EXE 不存在是连带现象。查看 ' + $log + ' 的第一条 error/CS****/MC****/XDG****。') }
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    $bins = @(Get-ChildItem -Path 'src\Dts.Wpf\bin' -Filter '*.exe' -Recurse -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName)
    throw ('编译返回成功但默认路径没有 EXE。检查配置：' + $exe + "`n查找到的 EXE：" + ($bins -join ', '))
}
Write-Host ('[PASS] 主程序 EXE 已存在：' + $exe)
Write-Host '[3/3] 编译并运行不接硬件的模块自检'
& dotnet run --project src/Dts.SelfTest/Dts.SelfTest.csproj -c $Configuration -p:UseAppHost=true 2>&1 | Tee-Object -FilePath $log -Append
if ($LASTEXITCODE -ne 0) { throw ('自检失败。主程序已生成，但需要查看 ' + $log) }
Write-Host '[PASS] 模块自检成功。' -ForegroundColor Green
if ($Run) {
    Write-Host '即将启动真实设备上位机：不会自动发出转台运动指令。'
    & $exe
}
Write-Host ('检查完毕。编译日志：' + $log)
