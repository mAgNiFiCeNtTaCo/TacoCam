; Taco Cam for Windows: the installer (Inno Setup 6). Built by pc/tools/build_portable.py from the same folder as
; dist\TacoCam.zip (build\portable\stage\Taco Cam):
;   ISCC.exe /DAppVersion=1.0 /DStage=<that folder> installer\TacoCam.iss   ->  dist\TacoCam-Setup-1.0.exe
;
; Installs for the current Windows user only (no admin): %LOCALAPPDATA%\Programs\Taco Cam. Taco Cam keeps its
; settings.json and taco-cam.log in that folder, so an update keeps the settings (settings.json is only written by
; a first install). The "Taco Cam" camera for OBS needs admin and is installed from the Get started window.
; Silent install (tests): TacoCam-Setup-1.0.exe /VERYSILENT /SUPPRESSMSGBOXES /DIR="<folder>" /TASKS="" /NOICONS

#define AppName "Taco Cam"
#ifndef AppVersion
  #define AppVersion "1.0"
#endif
#ifndef Stage
  #define Stage "..\build\portable\stage\Taco Cam"
#endif
#define Pyw "{app}\python\pythonw.exe"
#define Py "{app}\python\python.exe"

[Setup]
AppId={{7AF629EA-3D95-47BC-82F8-F0D22B6F091F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Taco Cam
AppPublisherURL=https://github.com/mAgNiFiCeNtTaCo/TacoCam
AppComments=Your phone as a USB webcam for OBS, with the 0.5x ultra-wide lens.
DefaultDirName={autopf}\Taco Cam
DefaultGroupName=Taco Cam
DisableProgramGroupPage=yes
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=TacoCam-Setup-{#AppVersion}
SetupIconFile={#Stage}\pc\tacocam\assets\taco-cam.ico
UninstallDisplayIcon={app}\pc\tacocam\assets\taco-cam.ico
UninstallDisplayName={#AppName}
LicenseFile={#Stage}\LICENSE.txt
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Put a Taco Cam icon on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#Stage}\*"; DestDir: "{app}"; Excludes: "settings.json,Start Taco Cam.cmd"; Flags: recursesubdirs createallsubdirs ignoreversion
; The starting settings (Android phone, Whatnot output): only on a first install, so an update keeps the friend's own.
Source: "{#Stage}\settings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist

[Icons]
Name: "{group}\Taco Cam"; Filename: "{#Pyw}"; Parameters: "-m tacocam"; WorkingDir: "{app}\pc"; IconFilename: "{app}\pc\tacocam\assets\taco-cam.ico"; AppUserModelID: "TacoCam.PC"; Comment: "Use your phone as the Taco Cam webcam in OBS"
Name: "{group}\How to set up Taco Cam"; Filename: "{app}\How to set up Taco Cam.html"
Name: "{autodesktop}\Taco Cam"; Filename: "{#Pyw}"; Parameters: "-m tacocam"; WorkingDir: "{app}\pc"; IconFilename: "{app}\pc\tacocam\assets\taco-cam.ico"; AppUserModelID: "TacoCam.PC"; Comment: "Use your phone as the Taco Cam webcam in OBS"; Tasks: desktopicon

[Run]
Filename: "{#Pyw}"; Parameters: "-m tacocam"; WorkingDir: "{app}\pc"; Description: "Open Taco Cam now"; Flags: postinstall nowait skipifsilent
Filename: "{app}\How to set up Taco Cam.html"; Description: "Read the setup guide"; Flags: postinstall shellexec nowait skipifsilent unchecked

[UninstallDelete]
; What Taco Cam writes next to itself while it runs (the phone app's copy on the phone stays; Android removes it
; like any app).
Type: files; Name: "{app}\settings.json"
Type: files; Name: "{app}\settings.bad.json"
Type: files; Name: "{app}\taco-cam.log*"
; Python's compiled files: Taco Cam keeps them in its own folder tacocam-cache (pc\tacocam\__init__.py); only that
; file itself is compiled before the folder is chosen. Never whole folders with everyday names like pc or python:
; the person may have picked a folder that holds their own (security finding WEBCAM-20261128-05).
Type: filesandordirs; Name: "{app}\tacocam-cache"
Type: filesandordirs; Name: "{app}\pc\tacocam\__pycache__"
; Folders the setup made, removed only when nothing is left in them.
Type: dirifempty; Name: "{app}\pc\tacocam"
Type: dirifempty; Name: "{app}\pc"
Type: dirifempty; Name: "{app}\python"
Type: dirifempty; Name: "{app}"

[Code]
{ A folder that already holds something other than Taco Cam is refused: the setup and the uninstaller then only
  ever deal with files Taco Cam put there. }
function FolderIsInUse(Dir: String): Boolean;
var
  Rec: TFindRec;
begin
  Result := False;
  if FileExists(AddBackslash(Dir) + 'pc\tacocam\__main__.py') then
    exit;                                             { an earlier Taco Cam: updating it is fine }
  if FindFirst(AddBackslash(Dir) + '*', Rec) then
  begin
    try
      repeat
        if (Rec.Name <> '.') and (Rec.Name <> '..') then
          Result := True;
      until Result or not FindNext(Rec);
    finally
      FindClose(Rec);
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID = wpSelectDir) and FolderIsInUse(WizardDirValue) then
  begin
    MsgBox('That folder already has other files in it.' + #13#10 + #13#10 +
      'Pick an empty folder, or a new one such as "' + AddBackslash(WizardDirValue) + 'Taco Cam".',
      mbError, MB_OK);
    Result := False;
  end;
end;

{ The same check for a silent install, which shows no folder page. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if FolderIsInUse(ExpandConstant('{app}')) then
    Result := 'The folder ' + ExpandConstant('{app}') + ' already has other files in it. Pick an empty folder.';
end;

{ Uninstalling: turn off the "Open Taco Cam when I log in" shortcut, but only when it starts this copy (another
  Taco Cam on this PC keeps its own). Then offer to remove the "Taco Cam" camera from OBS (needs admin; No by
  default, because another Taco Cam on this PC may use the same camera). }
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Code: Integer;
  Bat: String;
begin
  if CurUninstallStep = usUninstall then
  begin
    if FileExists(ExpandConstant('{#Py}')) then
      Exec(ExpandConstant('{#Py}'),
        '-B -c "import sys; from tacocam import shortcuts; shortcuts.remove_autostart_of(sys.argv[1])" "' +
        ExpandConstant('{app}') + '"', ExpandConstant('{app}\pc'), SW_HIDE, ewWaitUntilTerminated, Code);
    Bat := ExpandConstant('{app}\pc\vcam\Uninstall Taco Cam camera.bat');
    if (not UninstallSilent) and FileExists(Bat) and
       (MsgBox('Also remove the "Taco Cam" camera from OBS?' + #13#10 + #13#10 +
         'Click No if another copy of Taco Cam on this PC still uses it. Removing it asks Windows for permission.',
         mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
      { Already as admin, so the script doesn't restart itself and this waits for it: its files are removed
        right after this step. }
      ShellExec('runas', Bat, '', ExpandConstant('{app}\pc\vcam'), SW_SHOW, ewWaitUntilTerminated, Code);
  end;
end;
