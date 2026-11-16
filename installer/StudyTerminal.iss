; Inno Setup script for Study Terminal.  Built by scripts\build-installer.ps1 after PyInstaller.
; Per-user install (no administrator rights needed). Your data lives in %LOCALAPPDATA%\StudyTerminal,
; separate from the program, so updating or reinstalling never touches your journal or paper account.

#define AppName "Study Terminal"
#ifndef AppVersion
  #define AppVersion "0.18.1"
#endif

[Setup]
AppId={{1EF5721A-B098-56C4-ADD1-28AF9D22F2D1}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=studyflp
DefaultDirName={localappdata}\Programs\Study Terminal
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist-installer
OutputBaseFilename=StudyTerminal-Setup-{#AppVersion}
SetupIconFile=..\desktop\assets\study-terminal.ico
UninstallDisplayIcon={app}\StudyTerminal.exe
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; closes a running copy before upgrading (the app shuts down cleanly on the close request)
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start Study Terminal (minimized to the tray) when I sign in to Windows"; GroupDescription: "Startup:"; Flags: unchecked

[Files]
Source: "..\dist\StudyTerminal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\StudyTerminal.exe"
Name: "{group}\{#AppName} logs"; Filename: "{localappdata}\StudyTerminal\logs"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\StudyTerminal.exe"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\StudyTerminal.exe"; Parameters: "--minimized"; Tasks: startup

[Dirs]
Name: "{localappdata}\StudyTerminal\logs"

[Run]
Filename: "{app}\StudyTerminal.exe"; Description: "Open Study Terminal now"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; the app's own "start on login" setting writes this file
Type: files; Name: "{userstartup}\StudyTerminal.cmd"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\StudyTerminal');
    if DirExists(DataDir) then
      { SuppressibleMsgBox: a silent uninstall (/SUPPRESSMSGBOXES) answers No, so data is only deleted when you click Yes yourself }
      if SuppressibleMsgBox('Also delete your Study Terminal data?' #13#10#13#10 +
                'This is your journal, practice accounts, settings, saved backtests and logs in:' #13#10 + DataDir + #13#10#13#10 +
                'Choose No to keep it (a later reinstall will pick it up again).',
                mbConfirmation, MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES then
        DelTree(DataDir, True, True, True);
  end;
end;
