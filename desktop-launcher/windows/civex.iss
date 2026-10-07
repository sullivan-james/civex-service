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

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

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
// After uninstalling, offer to remove what the launcher downloaded (civex
// and its Python). Projects live wherever their folders are and are never
// touched. A silent uninstall keeps it, so a scripted one never deletes more
// than it was asked to.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Downloaded: String;
begin
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
