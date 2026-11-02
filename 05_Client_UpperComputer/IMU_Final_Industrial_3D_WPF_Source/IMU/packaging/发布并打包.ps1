param(
    [switch]$SkipTests,
    [switch]$NoInstaller
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$solution = Join-Path $projectRoot 'DynamicInclinometer.slnx'
$appProject = Join-Path $projectRoot 'src\DynamicInclinometer.App\DynamicInclinometer.App.csproj'
$testProject = Join-Path $projectRoot 'tests\DynamicInclinometer.SmokeTests\DynamicInclinometer.SmokeTests.csproj'
$sampleCal = Join-Path $projectRoot 'samples\accel_calibration_device_0002.json'
$publishDir = Join-Path $projectRoot 'publish\win-x64'
$distDir = Join-Path $projectRoot 'dist'
$issFile = Join-Path $PSScriptRoot 'DynamicInclinometerLab.iss'

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw '未找到 dotnet。请在 Windows 安装 .NET 10 SDK 后重试。'
}
if (-not (Test-Path $appProject)) {
    throw "找不到 WPF 项目：$appProject；请将 packaging 文件夹放在工程根目录。"
}

Set-Location $projectRoot
New-Item -ItemType Directory -Force -Path $distDir | Out-Null

Write-Host '[1/4] 还原 NuGet 包...' -ForegroundColor Cyan
& dotnet restore $solution
if ($LASTEXITCODE -ne 0) { throw 'dotnet restore 失败；请查看上面的错误。' }

if (-not $SkipTests) {
    Write-Host '[2/4] 执行基础算法/协议测试...' -ForegroundColor Cyan
    & dotnet run --project $testProject -c Release -- $sampleCal
    if ($LASTEXITCODE -ne 0) { throw 'SmokeTests 未通过，停止打包。' }
} else {
    Write-Warning '已跳过基础测试。该构建不可作为正式发布验收依据。'
}

Write-Host '[3/4] 发布 Windows x64 自包含应用...' -ForegroundColor Cyan
if (Test-Path $publishDir) { Remove-Item -LiteralPath $publishDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $publishDir | Out-Null
& dotnet publish $appProject -c Release -r win-x64 --self-contained true `
    '-p:PublishSingleFile=false' '-p:PublishTrimmed=false' '-p:PublishReadyToRun=false' `
    -o $publishDir
if ($LASTEXITCODE -ne 0) { throw 'dotnet publish 失败，未生成安装包。' }

$exe = Join-Path $publishDir 'DynamicInclinometer.App.exe'
$dll = Join-Path $publishDir '2TD600.dll'
if (-not (Test-Path $exe)) { throw "发布缺少程序 EXE: $exe" }
if (-not (Test-Path $dll)) { throw '发布缺少厂商 2TD600.dll。请检查 WPF csproj 的复制设置。' }

Write-Host '[4/4] 制作便携 ZIP / 可选 Setup.exe...' -ForegroundColor Cyan
$portableZip = Join-Path $distDir 'DynamicInclinometerLab_Engineering_0.3.0_win-x64_Portable.zip'
if (Test-Path $portableZip) { Remove-Item $portableZip -Force }
Compress-Archive -Path (Join-Path $publishDir '*') -DestinationPath $portableZip -CompressionLevel Optimal

if (-not $NoInstaller) {
    $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    $isccPath = if ($iscc) { $iscc.Source } else { $null }
    if (-not $isccPath) {
        foreach ($candidate in @(
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 7\ISCC.exe')
        )) {
            if ($candidate -and (Test-Path $candidate)) { $isccPath = $candidate; break }
        }
    }
    if ($isccPath) {
        & $isccPath $issFile
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup 编译安装程序失败。便携 ZIP 仍然可用。' }
    } else {
        Write-Warning '未找到 Inno Setup；已生成便携 ZIP。安装 Inno Setup 6/7 后再次运行即可生成 Setup.exe。'
    }
}

$hashFile = Join-Path $distDir 'SHA256.txt'
$lines = Get-ChildItem $distDir -File | Where-Object { $_.Name -ne 'SHA256.txt' } | Sort-Object Name | ForEach-Object {
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash
    "$hash  $($_.Name)"
}
Set-Content -LiteralPath $hashFile -Value $lines -Encoding UTF8
Write-Host "发布成功。输出目录：$distDir" -ForegroundColor Green
Write-Warning '该构建仍需在真实 Windows 机器上做启动、COM 通信、DLL、校准、数据落盘等验收；不得将未验证的研发功能声明为正式产品功能。'
