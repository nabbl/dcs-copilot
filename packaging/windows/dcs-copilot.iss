#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef ServiceUrl
  #define ServiceUrl "ws://127.0.0.1:8000/v2/realtime"
#endif

#define AppName "DCS Copilot"
#define Publisher "DCS Copilot"
#define RepoRoot AddBackslash(SourcePath) + "..\.."
#define DistRoot RepoRoot + "\dist\windows"

[Setup]
AppId={{21884D19-55C5-4C47-A39A-BEBC96B95547}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={autopf}\DCS Copilot
DefaultGroupName=DCS Copilot
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
OutputDir={#DistRoot}
OutputBaseFilename=DCS-Copilot-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\DCS Copilot\DCS Copilot.exe
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#Publisher}
VersionInfoDescription=DCS Copilot Windows installer

[Files]
Source: "{#DistRoot}\DCS Copilot\*"; DestDir: "{app}\DCS Copilot"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistRoot}\dcs-copilot\*"; DestDir: "{app}\dcs-copilot"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\DCS Copilot"; Filename: "{app}\DCS Copilot\DCS Copilot.exe"
Name: "{autodesktop}\DCS Copilot"; Filename: "{app}\DCS Copilot\DCS Copilot.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "dcsbios"; Description: "Install or update DCS-BIOS in detected DCS Saved Games folders"; GroupDescription: "DCS integration:"; Flags: checkedonce

[Registry]
Root: HKCU; Subkey: "Software\DCS Copilot"; ValueType: string; ValueName: "ServiceUrl"; ValueData: "{#ServiceUrl}"; Flags: uninsdeletekeyifempty

[Run]
Filename: "{app}\dcs-copilot\dcs-copilot.exe"; Parameters: "setup-dcs"; Description: "Configure DCS-BIOS"; Flags: runhidden waituntilterminated; Tasks: dcsbios
Filename: "{app}\DCS Copilot\DCS Copilot.exe"; Description: "Launch DCS Copilot"; Flags: nowait postinstall skipifsilent
