; Inno Setup 6 script. Per-user install: no administrator rights needed.
; Built by build.ps1, which passes /DMyAppVersion=<version>.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#define MyAppName "AutoClicker Visual"
#define MyAppExe "AutoClickerVisual.exe"

[Setup]
AppId={{8F3C2A7E-5B1D-4E6A-9C2F-1A7B3D5E9F01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppName}
AppPublisherURL=https://github.com/anderescaray/autoclicker
DefaultDirName={localappdata}\Programs\AutoClickerVisual
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=AutoClickerVisual-Setup-{#MyAppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExe}
UninstallDisplayName={#MyAppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[InstallDelete]
; remove files of the previous version so old libraries never mix with new ones
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\AutoClickerVisual\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{userdesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

; Flows and settings in %APPDATA%\AutoClickerVisual are kept on uninstall on purpose.
