# Checks the concrete generated MSBuild editorconfig path before Visual Studio / dotnet build.
# No registry modifications, no environment changes, no motor commands.
param(
  [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
  [switch]$OnlyWarn
)
$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
$names = @('DynamicInclinometer.Infrastructure','DynamicInclinometer.Devices','DynamicInclinometer.Core','DynamicInclinometer.App')
$configs = @('Debug','Release')
$paths = foreach($name in $names) {
    foreach($cfg in $configs) {
        Join-Path $projectRoot ("src\{0}\obj\{1}\net10.0-windows\{0}.GeneratedMSBuildEditorConfig.editorconfig" -f $name,$cfg)
    }
}
$longest = $paths | Sort-Object Length -Descending | Select-Object -First 1
$count = $longest.Length
Write-Host ("工程路径检查：最长的自动生成文件路径约 {0} 字符" -f $count)
if($count -gt 240) {
   $msg = "构建路径较长（最长 $count 字符），容易遇到 Windows/MSBuild 260 字符路径限制。请先将 ZIP 直接解压至 D:\IMU 或 C:\IMU，重新用新目录里的 DynamicInclinometer.slnx 打开；不要继续用原先深层目录。"
   if($OnlyWarn) {Write-Warning $msg}
   else {throw $msg}
} else {
   Write-Host '工程路径长度正常。' -ForegroundColor Green
}
