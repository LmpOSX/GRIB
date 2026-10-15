; Instalador de Visor GRIB para Windows (Inno Setup 6).
; Lo invoca scripts\build_windows.ps1 después de PyInstaller:
;   ISCC /DMyAppVersion=0.1.0 /DOutputBase=Visor_GRIB_0.1.0_Windows_x64_Setup packaging\visor_grib.iss
#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif
#ifndef OutputBase
  #define OutputBase "Visor_GRIB_" + MyAppVersion + "_Windows_x64_Setup"
#endif
#define MyAppName "Visor GRIB"
#define MyAppPublisher "Visor GRIB"
#define MyAppURL "https://github.com/LmpOSX/GRIB"
#define MyAppExeName "VisorGRIB.exe"

[Setup]
AppId={{7E0C1B2A-5D3F-4C8E-9A61-2B4F7D9E1C30}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename={#OutputBase}
SetupIconFile=..\resources\VisorGRIB.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ChangesAssociations=yes
LicenseFile=
DisableProgramGroupPage=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "fileassoc"; Description: "Asociar los archivos .grib2 / .grb2 / .grib / .grb con {#MyAppName}"; GroupDescription: "Archivos:"

[Files]
Source: "..\dist\VisorGRIB\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\VisorGRIB.grib"; ValueType: string; ValueName: ""; ValueData: "Archivo GRIB"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\VisorGRIB.grib\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#MyAppExeName},0"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\VisorGRIB.grib\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#MyAppExeName}"" ""%1"""; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\.grib2"; ValueType: string; ValueName: ""; ValueData: "VisorGRIB.grib"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\.grb2"; ValueType: string; ValueName: ""; ValueData: "VisorGRIB.grib"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\.grib"; ValueType: string; ValueName: ""; ValueData: "VisorGRIB.grib"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\.grb"; ValueType: string; ValueName: ""; ValueData: "VisorGRIB.grib"; Flags: uninsdeletevalue; Tasks: fileassoc

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
