#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#ifndef ServiceUrl
  #define ServiceUrl "ws://127.0.0.1:47100/v2/realtime"
#endif

#define AppName "MARA"
#define Publisher "DCS Copilot"
#define RepoRoot AddBackslash(SourcePath) + "..\.."
#define DistRoot RepoRoot + "\dist\windows"

[Setup]
AppId={{21884D19-55C5-4C47-A39A-BEBC96B95547}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#Publisher}
DefaultDirName={autopf}\MARA
DefaultGroupName=MARA
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
OutputDir={#DistRoot}
OutputBaseFilename=MARA-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\DCS Copilot\DCS Copilot.exe
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#Publisher}
VersionInfoDescription=MARA Windows installer

[Files]
Source: "{#DistRoot}\DCS Copilot\*"; DestDir: "{app}\DCS Copilot"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistRoot}\dcs-copilot\*"; DestDir: "{app}\dcs-copilot"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#DistRoot}\MaraBackend\*"; DestDir: "{app}\MaraBackend"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#RepoRoot}\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\MARA"; Filename: "{app}\DCS Copilot\DCS Copilot.exe"
Name: "{autodesktop}\MARA"; Filename: "{app}\DCS Copilot\DCS Copilot.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "dcsbios"; Description: "Install or update DCS-BIOS in detected DCS Saved Games folders"; GroupDescription: "DCS integration:"; Flags: checkedonce

[Registry]
Root: HKCU; Subkey: "Software\DCS Copilot"; ValueType: string; ValueName: "ServiceUrl"; ValueData: "{#ServiceUrl}"; Flags: uninsdeletekeyifempty

[Run]
Filename: "{app}\dcs-copilot\dcs-copilot.exe"; Parameters: "setup-dcs"; Description: "Configure DCS-BIOS"; Flags: runhidden waituntilterminated; Tasks: dcsbios
Filename: "{app}\DCS Copilot\DCS Copilot.exe"; Description: "Launch MARA"; Flags: nowait postinstall skipifsilent
