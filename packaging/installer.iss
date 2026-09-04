; ===================================================================
;  Inno Setup script for the ENF Serial Command Console
;
;  Compile after running the PyInstaller build:
;      packaging\build.bat /installer
;  or manually:
;      "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\installer.iss
;
;  Packages the one-folder PyInstaller output, which starts noticeably
;  faster than the one-file build because nothing is unpacked to %TEMP%
;  on every launch. The single-file portable .exe is shipped separately.
; ===================================================================

#define AppName        "ENF Serial Command Console"
#define AppVersion     "1.0.0"
#define AppPublisher   "ENF"
#define AppExeName     "SerialCommandConsole.exe"
#define AppUrl         "https://github.com/hamid-enf/Serial_App"
#define SourceDir      "dist\SerialCommandConsole"

[Setup]
AppId={{8B2F1D6C-6B4B-4E4B-9C2B-2D4C7A9F1E30}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppCopyright=Copyright (c) 2026 ENF
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
OutputDir=installer_output
OutputBaseFilename=SerialCommandConsole-{#AppVersion}-setup
SetupIconFile=..\resources\icons\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user installs need no elevation; the wizard offers the choice.
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "portablemode"; Description: "Portable mode (keep settings next to the program instead of in %APPDATA%)"; GroupDescription: "Options:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceDir}\*";             DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\README.md";               DestDir: "{app}"; DestName: "README.md"; Flags: ignoreversion
Source: "..\LICENSE";                 DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExeName}"
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";        Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[InstallDelete]
; Remove the marker when the task is not selected, so re-running the
; installer can switch an existing installation back to %APPDATA%.
Type: files; Name: "{app}\portable.txt"; Tasks: not portablemode

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\data"
Type: dirifempty;     Name: "{app}"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  MarkerPath: String;
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('portablemode') then
    begin
      MarkerPath := ExpandConstant('{app}\portable.txt');
      SaveStringToFile(MarkerPath,
        'Settings and logs are stored in the "data" folder next to the executable.' + #13#10,
        False);
    end;
  end;
end;

function InitializeUninstall(): Boolean;
begin
  Result := True;
end;
