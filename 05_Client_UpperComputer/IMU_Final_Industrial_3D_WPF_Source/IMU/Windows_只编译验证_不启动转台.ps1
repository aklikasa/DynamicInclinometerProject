$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
# Preflight: catch Windows MAX_PATH errors before .NET reports a missing generated editorconfig.
& (Join-Path $PSScriptRoot 'tools\检查路径长度.ps1') -ProjectRoot $PSScriptRoot
Write-Host '=== WPF project build verification (no motor or serial commands) ===' -ForegroundColor Cyan
if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
  throw '.NET SDK 未找到；请安装 .NET 10 SDK / Visual Studio .NET 桌面开发工作负载。'
}
# Fail fast on actual XAML, shader, or C# compile problems.
dotnet build '.\src\DynamicInclinometer.App\DynamicInclinometer.App.csproj' -c Debug --nologo -v:minimal
if ($LASTEXITCODE -ne 0) { throw '编译失败：请复制本命令上方的第一条 error 错误，不要直接按 F5。' }
$exe = Join-Path $PSScriptRoot 'src\DynamicInclinometer.App\bin\Debug\net10.0-windows\DynamicInclinometer.App.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) { throw "DLL 已生成但是 EXE 不存在：$exe" }
$shaderSource = Join-Path $PSScriptRoot 'src\DynamicInclinometer.App\Effects\LiquidGlass.hlsl'
if (-not (Test-Path -LiteralPath $shaderSource -PathType Leaf)) { throw "缺少嵌入的 HLSL 源码：$shaderSource" }
Write-Host 'BUILD PASS: EXE 已生成，HLSL 源码作为 EmbeddedResource 嵌入主程序集。' -ForegroundColor Green
Write-Host '注意：运行时在 Windows 上才尝试编译 GPU 着色器；这个脚本不会启动软件或转台。' -ForegroundColor Yellow
Write-Host $exe
