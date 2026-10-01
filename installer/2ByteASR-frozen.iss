; Build only from the verified, clean frozen payload. No source checkout glob.
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef ReleaseDir
  #error ReleaseDir is required
#endif
#ifndef MyAppVersion
  #error MyAppVersion is required
#endif

[Setup]
AppId={code:ApplicationId}
#ifdef QAInstall
AppName=2ByteASR QA
DefaultDirName={localappdata}\Programs\2ByteASR-QA-20260927
OutputBaseFilename=2ByteASR-QA-Setup-{#MyAppVersion}
CloseApplications=no
UsePreviousAppDir=no
#else
AppName=2ByteASR
DefaultDirName={localappdata}\Programs\2ByteASR
OutputBaseFilename=2ByteASR-Setup-{#MyAppVersion}
CloseApplications=yes
#endif
UsePreviousLanguage=no
AppVersion={#MyAppVersion}
MinVersion=10.0.19045
DisableDirPage=no
AppPublisher=2ByteASR contributors
DefaultGroupName=2ByteASR
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
RestartApplications=no
OutputDir={#ReleaseDir}
SetupIconFile=..\assets\app_icon.ico
UninstallDisplayIcon={app}\2ByteASR.exe
LicenseFile={#PayloadDir}\LICENSE
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
AllowNoIcons=yes

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: checkedonce

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Excludes: "2byteasr_settings.json,game_profiles.json,glossary.txt"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#PayloadDir}\2byteasr_settings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#PayloadDir}\game_profiles.json"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall
Source: "{#PayloadDir}\glossary.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist uninsneveruninstall

[Icons]
Name: "{group}\2ByteASR"; Filename: "{app}\2ByteASR.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app_icon.ico"; AppUserModelID: "2ByteASR.Desktop.2026"; Check: NotAudit
Name: "{autodesktop}\2ByteASR"; Filename: "{app}\2ByteASR.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\app_icon.ico"; AppUserModelID: "2ByteASR.Desktop.2026"; Tasks: desktopicon; Check: NotAudit

[Run]
Filename: "{app}\2ByteASR.exe"; Description: "启动 2ByteASR"; WorkingDir: "{app}"; Flags: postinstall nowait skipifsilent; Check: NotAudit

; Inno removes only files it installed. Models, projects and per-user settings
; created later are intentionally retained; never recursively delete {app}.
[Code]
function NotAudit: Boolean;
begin
#ifdef QAInstall
  Result := False;
#else
  Result := ExpandConstant('{param:AUDIT|0}') <> '1';
#endif
end;

function ApplicationId(Param: String): String;
begin
#ifdef QAInstall
  Result := '{D2CA55A8-6992-4C39-BAF1-2D790E9B5E26}-ModelQA20260927';
#else
  if NotAudit then
    Result := '{D2CA55A8-6992-4C39-BAF1-2D790E9B5E26}'
  else
    Result := '{D2CA55A8-6992-4C39-BAF1-2D790E9B5E26}-IsolatedAudit';
#endif
end;
