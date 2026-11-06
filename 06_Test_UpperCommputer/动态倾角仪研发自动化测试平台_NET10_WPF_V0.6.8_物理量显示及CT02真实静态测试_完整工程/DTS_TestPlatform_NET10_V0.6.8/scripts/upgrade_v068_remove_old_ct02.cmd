@echo off
setlocal
set "ROOT=%~dp0.."
if not exist "%ROOT%\DTS.TestPlatform.sln" (
  echo [ERROR] This script must be in the project scripts folder.
  exit /b 1
)
set "OLD=%ROOT%\src\Dts.Tests\S1\CT_02_Test.cs"
set "NEW=%ROOT%\src\Dts.Tests\S1\CT02\CT_02_Test.cs"
if not exist "%NEW%" (
  echo [ERROR] Copy the V0.6.8 patch files first. New CT02 module was not found.
  exit /b 1
)
if exist "%OLD%" (
  del /f /q "%OLD%"
  if exist "%OLD%" (
    echo [ERROR] Failed to delete old CT_02_Test.cs placeholder.
    exit /b 1
  )
)
echo [OK] Old CT-02 placeholder removed; only modular S1\CT02\CT_02_Test.cs remains.
echo Next: Visual Studio -- Clean Solution -- Rebuild Solution.
exit /b 0
