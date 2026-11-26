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
; Python's __pycache__ folders appear all over its own two folders while Taco Cam runs: remove those folders whole.
Type: filesandordirs; Name: "{app}\pc"
Type: filesandordirs; Name: "{app}\python"

[Code]
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
        '-c "import sys; from tacocam import shortcuts; shortcuts.remove_autostart_of(sys.argv[1])" "' +
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
