#ifndef MyAppVersion
  #define MyAppVersion "0.1.0-dev"
#endif
#define MyAppName "2ByteASR"
#define MyAppPublisher "2ByteASR contributors"
#define MyAppExeName "2ByteASR.exe"
#define MyAppUserModelId "2ByteASR.Desktop.2026"

[Setup]
AppId={{D2CA55A8-6992-4C39-BAF1-2D790E9B5E26}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\{#MyAppName}
UsePreviousAppDir=yes
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 安装前自动关闭运行中的 2ByteASR（避免“无法关闭/文件占用”后需 try again/ignore）
AppMutex=2ByteASR.Desktop.2026
CloseApplications=yes
RestartApplications=yes
OutputDir=..\dist
OutputBaseFilename=2ByteASR-Setup-{#MyAppVersion}
SetupIconFile=..\assets\2byteasr.ico
; Setup 只创建轻量工作台环境；模型及其专属依赖由模型工坊按需安装。
; 这里预留约 3 GB 给安装包文件、单个基础 Python 环境和临时空间。
ExtraDiskSpaceRequired=3221225472
UninstallDisplayIcon={app}\{#MyAppExeName}
LicenseFile=..\LICENSE
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
#ifdef MySignTool
SignTool={#MySignTool}
SignedUninstaller=yes
#endif

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式："; Flags: checkedonce

[Files]
#ifdef MySignTool
Source: "..\2ByteASR.exe"; DestDir: "{app}"; Flags: ignoreversion signonce
#else
Source: "..\2ByteASR.exe"; DestDir: "{app}"; Flags: ignoreversion
#endif
Source: "..\2ByteASR-Configure.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\*.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\*.bat"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\*.json"; DestDir: "{app}"; Excludes: "secrets.json,2byteasr_settings.json,game_profiles.json"; Flags: ignoreversion
Source: "..\2byteasr_settings.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\game_profiles.json"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\*.txt"; DestDir: "{app}"; Excludes: "glossary.txt"; Flags: ignoreversion
Source: "..\glossary.txt"; DestDir: "{app}"; Flags: onlyifdoesntexist
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CHANGELOG.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\CONFIGURATION.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\TERMINOLOGY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\SECRETS_SETUP.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\UPDATING.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\twobyteasr\*.py"; DestDir: "{app}\twobyteasr"; Flags: ignoreversion
Source: "..\lexicons\*.json"; DestDir: "{app}\lexicons"; Flags: ignoreversion
Source: "..\assets\*"; DestDir: "{app}\assets"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\scripts\*.ps1"; DestDir: "{app}\scripts"; Flags: ignoreversion
Source: "..\scripts\download_file_fast.py"; DestDir: "{app}\scripts"; Flags: ignoreversion
; 内置工具链（tools/）：git/ffmpeg/python 安装器/uv —— 首次配置零工具下载
Source: "..\tools\*"; DestDir: "{app}\tools"; Flags: ignoreversion recursesubdirs createallsubdirs
; 可选离线依赖（本地发布构建会提供；CI 轻量构建没有时自动退回联网安装）
Source: "..\wheels\*"; DestDir: "{app}\wheels"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist
; 固定版本源码（third_party/）：随包分发，首次配置不再从 GitHub 拉取
; build_installer.ps1 会先移除 .git/tests/__pycache__/egg-info 等开发残留。
Source: "..\tmp\installer-third-party\*"; DestDir: "{app}\third_party"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\2byteasr.ico"; AppUserModelID: "{#MyAppUserModelId}"
Name: "{group}\配置或修复 {#MyAppName}"; Filename: "{app}\2ByteASR-Configure.exe"; WorkingDir: "{app}"; IconFilename: "{app}\assets\2byteasr.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; IconFilename: "{app}\assets\2byteasr.ico"; AppUserModelID: "{#MyAppUserModelId}"; Tasks: desktopicon

[Run]
; 图形配置器实时显示日志并提供原地重试。没有 nowait：用户关闭配置器前，
; Setup 完成页会继续保留在后方；全程不再启动 CMD 窗口。
Filename: "{app}\2ByteASR-Configure.exe"; Description: "配置 2ByteASR 运行环境（失败可直接重试）"; WorkingDir: "{app}"; Flags: postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.venv-main"
Type: filesandordirs; Name: "{app}\.venv-moss"
Type: filesandordirs; Name: "{app}\models"
Type: filesandordirs; Name: "{app}\third_party"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\twobyteasr\__pycache__"
