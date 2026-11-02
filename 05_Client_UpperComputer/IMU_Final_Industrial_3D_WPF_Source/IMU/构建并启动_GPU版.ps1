$ErrorActionPreference="Stop"
Set-Location $PSScriptRoot
# Preflight: catch Windows MAX_PATH errors before .NET reports a missing generated editorconfig.
& (Join-Path $PSScriptRoot 'tools\检查路径长度.ps1') -ProjectRoot $PSScriptRoot
$proj="src\DynamicInclinometer.App\DynamicInclinometer.App.csproj"
Write-Host "检查 .NET SDK..."
dotnet --version
Write-Host "编译 WPF / HLSL (Debug)"
dotnet build $proj -c Debug -v:minimal
if ($LASTEXITCODE -ne 0) { throw "构建失败，请检查上方第一条错误。" }
$exe=Join-Path $PSScriptRoot "src\DynamicInclinometer.App\bin\Debug\net10.0-windows\DynamicInclinometer.App.exe"
if (-not (Test-Path $exe)) { throw "构建返回成功，但找不到EXE：$exe。请检查UseAppHost和构建输出目录。" }
Write-Host "EXE已生成：$exe"
Start-Process -FilePath $exe -WorkingDirectory (Split-Path $exe)
