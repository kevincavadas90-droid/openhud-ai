; OpenHUD AI — Inno Setup script (official Windows installer).
;
; Build the app first:   python -m openhud.desktop.build
; Then compile this:     iscc installer\openhud.iss
; Result:                 installer\Output\OpenHUD-AI-Setup.exe
;
; Clean-install guarantees:
;   * installs into {autopf}\OpenHUD AI by default (per-user if not elevated);
;   * desktop / start-menu icons are OPTIONAL (unchecked by default);
;   * "start with Windows" is OPTIONAL and unchecked by default;
;   * no services, no scheduled tasks, no hidden startup entries;
;   * the uninstaller removes the app's own files and asks whether to keep
;     the user's local data;
;   * nothing else is left behind.

#define MyAppName "OpenHUD AI"
#ifndef MyAppVersion
  #define MyAppVersion "5.1.1"
#endif
#define MyAppPublisher "OpenHUD"
#define MyAppURL "https://github.com/"
#define MyAppExeName "OpenHUD AI.exe"
#define MyAgentExeName "openhud-agent.exe"

[Setup]
AppId={{9F3C1B2A-7E4D-4C11-9A3E-OPENHUD0001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} Setup
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableWelcomePage=no
LicenseFile=..\LICENSE
OutputDir=Output
OutputBaseFilename=OpenHUD-AI-Setup
SetupIconFile=openhud.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Per-user install by default; the user may choose an all-users install.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na área de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked
Name: "startmenuicon"; Description: "Criar um atalho no menu Iniciar"; GroupDescription: "Atalhos:"; Flags: unchecked
Name: "autostart"; Description: "Iniciar o OpenHUD com o Windows (opcional)"; GroupDescription: "Inicialização:"; Flags: unchecked

[Files]
Source: "..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\{#MyAgentExeName}"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion isreadme
Source: "..\WINDOWS_TEST.md"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist
Source: "openhud.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\openhud.ico"; Tasks: desktopicon
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\openhud.ico"; Tasks: startmenuicon

[Registry]
; Startup entry only if the user explicitly asked for it.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "OpenHUD AI"; ValueData: """{app}\{#MyAppExeName}"" --no-browser"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir o OpenHUD agora"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
var
  RemoveData: Boolean;

function InitializeUninstall(): Boolean;
begin
  Result := True;
  RemoveData := MsgBox('Deseja também apagar seus dados locais do OpenHUD' +
    ' (conversas, memória, senha local)?' + #13#10 + #13#10 +
    'Escolha Não para mantê-los para uma futura reinstalação.',
    mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if (CurUninstallStep = usPostUninstall) and RemoveData then
  begin
    DataDir := ExpandConstant('{userappdata}\OpenHUD');
    DelTree(DataDir, True, True, True);
  end;
end;
