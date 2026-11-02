#define AppTitle "Dynamic Inclinometer Lab (Engineering)"
#define AppExe "DynamicInclinometer.App.exe"
#define AppVersion "0.3.0"

[Setup]
AppId=DynamicInclinometerLab.Engineering
AppName={#AppTitle}
AppVersion={#AppVersion}
AppVerName={#AppTitle} {#AppVersion}
DefaultDirName={localappdata}\Programs\DynamicInclinometerLab
DefaultGroupName=Dynamic Inclinometer Lab
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=DynamicInclinometerLab_Engineering_0.3.0_win-x64_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExe}
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式:"; Flags: unchecked

[Files]
; 安装 WPF publish 的完整文件夹。保留 2TD600.dll 和其它依赖。
Source: "..\publish\win-x64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "安装须知.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Dynamic Inclinometer Lab"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"
Name: "{userdesktop}\Dynamic Inclinometer Lab"; Filename: "{app}\{#AppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

; 有意不在安装结束后自动启动：先完成设备连接和试验安全确认。
