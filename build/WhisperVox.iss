; Whisper Vox - voice dictation.
; Copyright (C) 2026 Pekelni Boroshna Lab.
;
; This program is free software: you can redistribute it and/or modify it under
; the terms of the GNU General Public License v3.0 as published by the Free
; Software Foundation. It comes with NO WARRANTY. See <https://www.gnu.org/licenses/>.
; SPDX-License-Identifier: GPL-3.0-or-later
;
; The Windows installer. Per-user, and it never asks for administrator rights.
; build_all.ps1 compiles it with the version it decided on:
;
;   ISCC.exe /DAppVersion=1.3.7 /DAppFileVersion=1.3.7 /DSourceDir=...\dist\WhisperVox
;            /DOutputDir=...\release /DOutputBase=WhisperVox-Setup-v1.3.7 build\WhisperVox.iss
;
; Keep this file ASCII: Inno reads a script without a BOM as ANSI.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppFileVersion
  #define AppFileVersion "0.0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\WhisperVox"
#endif
#ifndef OutputDir
  #define OutputDir "..\release"
#endif
#ifndef OutputBase
  #define OutputBase "WhisperVox-Setup"
#endif

; NEVER change this. It is how Windows recognises every later version as the
; same program - its Apps & Features entry and the folder it was installed to.
#define AppGuid "7B5BD57A-FE69-4388-A377-D987F0D91F5B"

; The app's identity as far as the Windows shell is concerned. MUST match
; APP_USER_MODEL_ID in src/platforms/win.py: the running process and its
; Start-Menu shortcut have to agree, or Windows cannot file the app's
; notifications under it.
#define AppUserModelID "PekelniBoroshnaLab.WhisperVox"

; Shared with the app (src/platforms/win.py). The app holds the mutex while it
; runs and quits when the event is set - the same handshake the old installer
; used, so a running 1.2.0 or 1.3.x understands it too.
#define AppMutex  "WhisperVoxApp_Mutex_v1"
#define QuitEvent "WhisperVoxApp_Quit_v1"

; The Apps & Features entry of the OLD installer (build/launcher.py, up to 1.3.x).
; Removed on install, or the app would be listed twice.
#define OldUninstallKey "Software\Microsoft\Windows\CurrentVersion\Uninstall\WhisperVox"

[Setup]
AppId={{{#AppGuid}
AppName=Whisper Vox
AppVersion={#AppVersion}
AppVerName=Whisper Vox {#AppVersion}
AppPublisher=Pekelni Boroshna Lab
AppPublisherURL=https://github.com/whisper-vox/whisper-vox
AppSupportURL=https://github.com/whisper-vox/whisper-vox/issues
AppUpdatesURL=https://github.com/whisper-vox/whisper-vox/releases
AppCopyright=Copyright (C) 2026 Pekelni Boroshna Lab

; Per-user and ONLY per-user. There is deliberately no
; PrivilegesRequiredOverridesAllowed, so setup never offers an all-users
; install and never raises a UAC prompt. {autopf} then resolves to
; %LOCALAPPDATA%\Programs - where the old installer put the app as well.
PrivilegesRequired=lowest
DefaultDirName={code:DefaultInstallDir}
UsePreviousAppDir=yes
DirExistsWarning=no
DisableProgramGroupPage=yes

; No summary page on a fresh install: it only repeated the folder chosen one
; page earlier, so the folder page's button says Install instead. On an update
; the folder page is skipped, the summary becomes the FIRST page, and Inno keeps
; it regardless - interactive setup must show at least one page, so there is a
; chance to cancel. CurPageChanged rewrites it into an honest "update" page.
DisableReadyPage=yes
; Nothing to decide at the end: the app is started by [Run] and setup closes.
DisableFinishedPage=yes

ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir={#OutputDir}
OutputBaseFilename={#OutputBase}
SetupIconFile=..\assets\wv-logo.ico
UninstallDisplayIcon={app}\WhisperVox.exe
UninstallDisplayName=Whisper Vox
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
SetupMutex=WhisperVoxSetup_Mutex_v1

; Our own handshake closes the app (PrepareToInstall below). Restart Manager
; stays on as the safety net for anything else still holding one of its files.
; [Run] starts the new version, so Restart Manager must not start one as well.
CloseApplications=yes
RestartApplications=no

VersionInfoVersion={#AppFileVersion}
VersionInfoTextVersion={#AppVersion}
VersionInfoProductVersion={#AppFileVersion}
VersionInfoProductTextVersion={#AppVersion}
VersionInfoProductName=Whisper Vox
VersionInfoCompany=Pekelni Boroshna Lab
VersionInfoDescription=Whisper Vox setup
VersionInfoCopyright=Copyright (C) 2026 Pekelni Boroshna Lab
; The name the file ships under inside the release zip. An empty or wrong one
; is one of the details that makes an unsigned binary look forged.
VersionInfoOriginalFileName=WhisperVox-Setup.exe

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[InstallDelete]
; A PyInstaller payload from an older build must not survive next to a newer
; one: stale modules in _internal are the kind of bug that only shows up on the
; machines that updated, never on a fresh install.
Type: filesandordirs; Name: "{app}\_internal"
; The old installer's copy of itself. Inno brings its own uninstaller now.
Type: files; Name: "{app}\uninstall.exe"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Whisper Vox"; Filename: "{app}\WhisperVox.exe"; WorkingDir: "{app}"; Comment: "Whisper Vox voice dictation"; AppUserModelID: "{#AppUserModelID}"

[Registry]
; The old installer's Apps & Features entry: deleted on install.
Root: HKCU; Subkey: "{#OldUninstallKey}"; ValueType: none; Flags: deletekey
; The app writes its version here itself; it goes when the app goes.
Root: HKCU; Subkey: "Software\WhisperVox"; ValueType: none; Flags: uninsdeletekey
; The app manages its own autostart. Setup only makes sure it does not outlive
; the app - an autostart entry pointing at a deleted exe fails at every login.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "WhisperVox"; ValueType: none; Flags: uninsdeletevalue

[UninstallDelete]
; The app creates its Desktop shortcut on its own (Misc > Desktop icon), so the
; uninstaller has no record of it. Both places: OneDrive's folder redirection
; moves the Desktop, and {userdesktop} follows it while the old path may not.
Type: files; Name: "{userdesktop}\Whisper Vox.lnk"
Type: files; Name: "{%USERPROFILE}\Desktop\Whisper Vox.lnk"

[Run]
; Not postinstall: that would put a "Launch" checkbox on a final page, and there
; is nothing to decide - an installed dictation tool that does not start is not
; a choice anyone makes. Without it the app starts as soon as the files are in,
; before setup closes, and it does so on a silent update too.
Filename: "{app}\WhisperVox.exe"; Flags: nowait

[Code]
const
  SYNCHRONIZE        = $00100000;
  EVENT_MODIFY_STATE = $0002;

// Declared by hand rather than through Inno's helpers, so the same code is
// guaranteed to work in the uninstaller too.
function OpenMutex(dwDesiredAccess: Cardinal; bInheritHandle: Integer; lpName: String): THandle;
  external 'OpenMutexW@kernel32.dll stdcall';
function OpenEvent(dwDesiredAccess: Cardinal; bInheritHandle: Integer; lpName: String): THandle;
  external 'OpenEventW@kernel32.dll stdcall';
function SetEvent(hEvent: THandle): Integer;
  external 'SetEvent@kernel32.dll stdcall';
function CloseHandle(hObject: THandle): Integer;
  external 'CloseHandle@kernel32.dll stdcall';
procedure KernelSleep(dwMilliseconds: Cardinal);
  external 'Sleep@kernel32.dll stdcall';

function AppIsRunning(): Boolean;
var
  H: THandle;
begin
  H := OpenMutex(SYNCHRONIZE, 0, '{#AppMutex}');
  Result := H <> 0;
  if Result then
    CloseHandle(H);
end;

// Ask a running copy to quit through the event it listens on, then wait for its
// mutex to go. Files cannot be replaced while the app holds them.
function CloseRunningApp(): Boolean;
var
  H: THandle;
  Waited: Integer;
begin
  Result := True;
  if not AppIsRunning() then
    exit;
  H := OpenEvent(EVENT_MODIFY_STATE, 0, '{#QuitEvent}');
  if H <> 0 then
  begin
    SetEvent(H);
    CloseHandle(H);
  end;
  Waited := 0;
  while AppIsRunning() and (Waited < 15000) do
  begin
    KernelSleep(100);
    Waited := Waited + 100;
  end;
  Result := not AppIsRunning();
end;

// Where the OLD installer put the app, or '' if it never did.
function OldInstallDir(): String;
begin
  if not RegQueryStringValue(HKCU, '{#OldUninstallKey}', 'InstallLocation', Result) then
    Result := '';
end;

// An update, as opposed to a first install: either this installer has been
// here before, or the old one has.
function IsUpgrade(): Boolean;
begin
  Result := RegKeyExists(HKCU,
              'Software\Microsoft\Windows\CurrentVersion\Uninstall\{' + '{#AppGuid}' + '}_is1')
            or (OldInstallDir() <> '');
end;

// Moving from the old installer: stay in the folder it used. An Inno install
// is covered by UsePreviousAppDir, which takes precedence over this.
function DefaultInstallDir(Param: String): String;
begin
  Result := OldInstallDir();
  if Result = '' then
    Result := ExpandConstant('{autopf}\WhisperVox');
end;

// An update goes where the app already is; asking again only invites a second
// copy somewhere else. Versions up to 1.3.x start the setup with no arguments,
// so this is the path they take.
function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := IsUpgrade() and (PageID = wpSelectDir);
end;

// The version being replaced, for the update page. The app records it itself
// on every start; the file next to the exe covers an app that never ran.
function InstalledVersion(): String;
var
  S: AnsiString;
begin
  if RegQueryStringValue(HKCU, 'Software\WhisperVox', 'Version', Result) and (Result <> '') then
    exit;
  Result := '';
  if LoadStringFromFile(ExpandConstant('{app}\.version'), S) then
    Result := Trim(String(S));
end;

// The summary Inno shows when it cannot skip the page. On an update that is
// the only page, so make it say something worth reading.
function UpdateReadyMemo(Space, NewLine, MemoUserInfoInfo, MemoDirInfo, MemoTypeInfo,
  MemoComponentsInfo, MemoGroupInfo, MemoTasksInfo: String): String;
var
  Old: String;
begin
  Result := MemoDirInfo;
  if not IsUpgrade() then
    exit;
  Old := InstalledVersion();
  Result := '';
  if Old <> '' then
    Result := 'Installed version:' + NewLine + Space + Old + NewLine + NewLine;
  Result := Result + 'New version:' + NewLine + Space + '{#AppVersion}' + NewLine + NewLine +
            MemoDirInfo + NewLine + NewLine +
            'Your settings and API key are kept.';
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  // Fresh install: the summary is skipped, so the folder page is the last
  // decision - its button has to say what it does. Inno does not relabel it.
  if CurPageID = wpSelectDir then
    WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall)
  // Update: the summary is the first and only page, so it has no Back button,
  // and Inno's stock text - "click Back if you want to review or change any
  // settings" - offers something that is not there.
  else if (CurPageID = wpReady) and IsUpgrade() then
  begin
    WizardForm.PageNameLabel.Caption := 'Ready to Update';
    WizardForm.PageDescriptionLabel.Caption := 'Setup is ready to update Whisper Vox on your computer.';
    WizardForm.ReadyLabel.Caption :=
      'Click Update to continue. Whisper Vox will be closed if it is running, ' +
      'and started again as soon as the update is done.';
    WizardForm.NextButton.Caption := 'Update';
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not CloseRunningApp() then
    Result := 'Whisper Vox is still running and could not be closed automatically.' + #13#10 + #13#10 +
              'Quit it from its tray icon near the clock (right-click, then Quit) and run this setup again.';
end;

function InitializeUninstall(): Boolean;
begin
  Result := CloseRunningApp();
  if not Result then
    MsgBox('Whisper Vox is still running and could not be closed automatically.' + #13#10 + #13#10 +
           'Quit it from its tray icon near the clock (right-click, then Quit) and try again.',
           mbError, MB_OK);
end;

// Settings live apart from the app, so removing the app keeps them unless the
// user says otherwise - reinstalling should not mean re-entering an API key.
// A silent uninstall never deletes them: nobody was asked.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  Settings: String;
begin
  if CurUninstallStep <> usPostUninstall then
    exit;
  Settings := ExpandConstant('{userappdata}\WhisperVox');
  if UninstallSilent() or not DirExists(Settings) then
    exit;
  if MsgBox('Also delete your personal settings?' + #13#10 + #13#10 +
            'That is your API key and preferences. Keep them if you might install Whisper Vox again.',
            mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    DelTree(Settings, True, True, True);
end;
