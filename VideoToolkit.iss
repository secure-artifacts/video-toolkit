[Setup]
AppName=VideoToolkit
AppVersion=1.7.6
DefaultDirName={localappdata}\Programs\VideoToolkit
DefaultGroupName=VideoToolkit
UninstallDisplayIcon={app}\VideoToolkit.exe
Compression=lzma2
SolidCompression=yes
OutputDir=.
OutputBaseFilename=VideoToolkit_Setup_v1.7.6
SetupIconFile=modules\icon.ico
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

[Files]
Source: "dist_folder\VideoToolkit\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs

[Icons]
Name: "{group}\VideoToolkit"; Filename: "{app}\VideoToolkit.exe"
Name: "{commondesktop}\VideoToolkit"; Filename: "{app}\VideoToolkit.exe"

[Run]
Filename: "{app}\VideoToolkit.exe"; Description: "运行 VideoToolkit"; Flags: postinstall nowait
