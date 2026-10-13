#define MyAppName "CampusNet"
#define MyAppVersion "0.5.9"
#define MyAppPublisher "CampusNet Project"

[Setup]
AppId={{B70AE1C1-4A64-4C5D-9A3C-8B2D53B85F6A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\CampusNet
DefaultGroupName=CampusNet
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
OutputDir=installer-output
OutputBaseFilename=CampusNet-Setup-{#MyAppVersion}
SetupIconFile=src\campusnet\assets\campusnet.ico
UninstallDisplayIcon={app}\CampusNet.exe
LicenseFile=LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "dist\CampusNet\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\CampusNet"; Filename: "{app}\CampusNet.exe"; IconFilename: "{app}\CampusNet.exe"
Name: "{autodesktop}\CampusNet"; Filename: "{app}\CampusNet.exe"; IconFilename: "{app}\CampusNet.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\CampusNet.exe"; Description: "Launch CampusNet"; Flags: nowait postinstall skipifsilent

; CampusNet manages the per-user Run entry from its Launch at startup setting.
; Remove that entry during uninstall so it doesn't point to a deleted executable.
[UninstallRun]
Filename: "{sys}\reg.exe"; Parameters: "delete ""HKCU\Software\Microsoft\Windows\CurrentVersion\Run"" /v ""CampusNet"" /f"; Flags: runhidden; RunOnceId: "RemoveCampusNetAutoStart"
