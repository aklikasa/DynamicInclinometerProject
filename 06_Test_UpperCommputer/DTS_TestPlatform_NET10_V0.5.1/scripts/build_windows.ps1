param([string]$Configuration = 'Debug')
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host '[1/4] Optional static preflight (Python is NOT required for this C# application)'
if (Get-Command python -ErrorAction SilentlyContinue) {
    python scripts/check_sources.py
    if ($LASTEXITCODE -ne 0) { throw 'Static check failed' }
} else {
    Write-Host 'Python not installed: skipping optional source static check.'
}
Write-Host '[2/4] Restore dependencies'
dotnet restore .\DTS.TestPlatform.sln
if ($LASTEXITCODE -ne 0) { throw 'Restore failed' }
Write-Host '[3/4] Compile all projects'
dotnet build .\DTS.TestPlatform.sln -c $Configuration --no-restore
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Write-Host '[4/4] Run C# module catalog self-test (no hardware required)'
dotnet run --project .\src\Dts.SelfTest\Dts.SelfTest.csproj -c $Configuration --no-build
if ($LASTEXITCODE -ne 0) { throw 'Self-test failed' }
Write-Host 'SUCCESS. Start Dts.Wpf in Visual Studio; hardware needs supervised validation.'
