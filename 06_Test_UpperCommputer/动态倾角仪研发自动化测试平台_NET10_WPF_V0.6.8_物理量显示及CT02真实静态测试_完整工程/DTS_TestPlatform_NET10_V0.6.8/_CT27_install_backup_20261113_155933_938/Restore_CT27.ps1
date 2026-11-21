[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$backup = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $backup
$placeholder = 'src/Dts.Tests/S1/CT_27_Test.cs'
$source = Join-Path $backup $placeholder
$target = Join-Path $root $placeholder
if (-not (Test-Path -LiteralPath $source -PathType Leaf)) { throw '原 CT-27 占位文件备份不存在，无法回滚。' }
Copy-Item -LiteralPath $source -Destination $target -Force
$remove = @(
 'src/Dts.Tests/S1/CT27/CT_27_Algorithm.cs',
 'src/Dts.Tests/S1/CT27/CT_27_Report.cs',
 'src/Dts.Tests/S1/CT27/CT_27_Result.cs',
 'src/Dts.Wpf/TestWindows/CT27/CT27Window.xaml',
 'src/Dts.Wpf/TestWindows/CT27/CT27Window.xaml.cs'
)
foreach ($r in $remove) { $p = Join-Path $root $r; if (Test-Path -LiteralPath $p -PathType Leaf) { Remove-Item -LiteralPath $p -Force } }
foreach ($d in @('src/Dts.Tests/S1/CT27','src/Dts.Wpf/TestWindows/CT27')) {
    $p = Join-Path $root $d
    if ((Test-Path -LiteralPath $p -PathType Container) -and -not (Get-ChildItem -LiteralPath $p -Force | Select-Object -First 1)) { Remove-Item -LiteralPath $p -Force }
}
Write-Host 'CT-27 rollback completed. Rebuild the solution in Visual Studio.' -ForegroundColor Green