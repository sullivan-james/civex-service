; Windows installer for the civex desktop app (Inno Setup 6).
;
;   iscc /DAppVersion=1.2.1 /DAppSource=C:\path\to\dist\civex /O<out dir> civex.iss
;
; Packs the launcher folder that desktop-launcher/launcher.spec builds. It
; installs for the current user only (no administrator prompt), beside where
; the launcher keeps civex itself (%LOCALAPPDATA%\civex\app), adds a Start menu
; entry and, if asked, a Desktop shortcut, and registers an uninstaller.
; Installing a newer version over an older one upgrades it in place.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppSource
  #define AppSource "..\..\dist\civex"
#endif

[Setup]
; Fixed for good: Windows recognises an installed civex by it, so a new
; installer upgrades the old one rather than installing a second copy.
AppId={{B70964A3-F05C-42B8-B38F-92F5B8F0C2C3}
AppName=civex
AppVersion={#AppVersion}
AppVerName=civex {#AppVersion}
AppPublisher=civex
AppPublisherURL=https://civexdata.github.io/civex-docs/
DefaultDirName={localappdata}\Programs\civex
DisableDirPage=auto
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; The release workflow names it for its version (iscc /F).
OutputBaseFilename=civex-setup-windows
SetupIconFile=..\assets\civex.ico
UninstallDisplayIcon={app}\civex.exe
UninstallDisplayName=civex
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; x64 build; also runs on Windows on ARM through its x64 emulation.
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Close a running civex before replacing it (an upgrade).
CloseApplications=yes
; Tell Windows when PATH changes (the "add to PATH" option), so new terminals
; see it.
ChangesEnvironment=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "addtopath"; Description: "Add the civex command to PATH, for terminals"; GroupDescription: "Command line:"

[Files]
Source: "{#AppSource}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\civex"; Filename: "{app}\civex.exe"
Name: "{autodesktop}\civex"; Filename: "{app}\civex.exe"; Tasks: desktopicon

[Run]
; Set civex up now, inside the wizard, so its first start opens straight into
; the app. Without a connection this fails quietly and the first start does
; it instead.
Filename: "{app}\civex.exe"; Parameters: "--install-only"; StatusMsg: "Setting up civex..."; Flags: runhidden waituntilterminated
Filename: "{app}\civex.exe"; Description: "{cm:LaunchProgram,civex}"; Flags: nowait postinstall skipifsilent

[Code]
// The civex command the app sets up lives in the launcher's folder. Putting
// that folder on the *user* PATH is the same entry Settings > Updates in the
// app reads and changes (civex/command_line.py), so the two always agree.
function CivexBin: String;
begin
  Result := ExpandConstant('{localappdata}\civex\app\bin');
end;

procedure AddCivexToPath;
var
  Paths: String;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
    Paths := '';
  if Pos(';' + Uppercase(CivexBin) + ';', ';' + Uppercase(Paths) + ';') > 0 then
    exit;
  if (Paths <> '') and (Copy(Paths, Length(Paths), 1) <> ';') then
    Paths := Paths + ';';
  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths + CivexBin);
end;

procedure RemoveCivexFromPath;
var
  Paths: String;
  At: Integer;
begin
  if not RegQueryStringValue(HKEY_CURRENT_USER, 'Environment', 'Path', Paths) then
    exit;
  Paths := ';' + Paths + ';';
  At := Pos(';' + Uppercase(CivexBin) + ';', Uppercase(Paths));
  if At = 0 then
    exit;
  Delete(Paths, At, Length(CivexBin) + 1);
  RegWriteExpandStringValue(HKEY_CURRENT_USER, 'Environment', 'Path',
    Copy(Paths, 2, Length(Paths) - 2));
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and WizardIsTaskSelected('addtopath') then
    AddCivexToPath;
end;

// After uninstalling, offer to remove what the launcher downloaded (civex
// and its Python). Projects live wherever their folders are and are never
// touched. A silent uninstall keeps it, so a scripted one never deletes more
// than it was asked to.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Downloaded: String;
begin
  // The command goes with the app, whoever put it on PATH.
  if CurUninstallStep = usUninstall then
    RemoveCivexFromPath;
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
  begin
    Downloaded := ExpandConstant('{localappdata}\civex\app');
    if DirExists(Downloaded) and (MsgBox(
      'Also remove the copy of civex and Python that civex downloaded?' + #13#10 + #13#10 +
      'Your projects are not touched. Keep it if you are reinstalling civex.',
      mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      DelTree(Downloaded, True, True, True);
  end;
end;
