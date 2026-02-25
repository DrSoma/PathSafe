; PathSafe Windows Installer Script (Inno Setup)
;
; To build manually:
;   1. Install Inno Setup from https://jrsoftware.org/isinfo.php
;   2. Build the PyInstaller executables first: pyinstaller pathsafe.spec
;   3. Run: iscc installer/pathsafe.iss
;
; The GitHub Actions workflow runs this automatically on release.

#define MyAppName "PathSafe"
#define MyAppVersion "1.0.2"
#define MyAppPublisher "PathSafe Contributors"
#define MyAppURL "https://github.com/DrSoma/PathSafe"
#define MyAppExeName "pathsafe-gui.exe"

[Setup]
AppId={{B3F8A2C1-7D4E-4F5A-9B6C-2E8D1A3F5C7B}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
LicenseFile=..\LICENSE
OutputDir=..\dist
OutputBaseFilename=PathSafe-Setup
SetupIconFile=..\pathsafe\assets\icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "addtopath"; Description: "Add PathSafe to system PATH (allows running from any terminal)"; GroupDescription: "Other:"

[Files]
Source: "..\dist\pathsafe-gui.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\pathsafe.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PathSafe"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PathSafe"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[Registry]
; Add to user PATH if the user selected that option
Root: HKCU; Subkey: "Environment"; ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; Tasks: addtopath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Code]
function NeedsAddPath(Param: string): boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + Param + ';', ';' + OrigPath + ';') = 0;
end;
