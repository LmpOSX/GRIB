; Instalador de Presupuestador Pro para Windows (Inno Setup 6)
;   iscc /DAppVersion=1.7.0 installer\windows\presupuestador.iss
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Presupuestador Pro"
#define AppExe "Presupuestador Pro.exe"
#define SrcDir "..\..\dist\Presupuestador Pro"

[Setup]
AppId={{7E2C3B1A-5F0B-4D7E-9D2A-3C1F2B9E7A10}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Presupuestador Pro
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExe}
OutputDir=..\..\dist
OutputBaseFilename=Presupuestador_Pro_{#AppVersion}_Setup
SetupIconFile=..\..\resources\PresupuestadorPro.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes
PrivilegesRequiredOverridesAllowed=dialog
PrivilegesRequired=lowest

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el Escritorio"; GroupDescription: "Accesos directos:"

[Files]
Source: "{#SrcDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\resources\PptoDocument.ico"; DestDir: "{app}\resources"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; Asociación de .ppto: doble clic abre el presupuesto
Root: HKA; Subkey: "Software\Classes\.ppto"; ValueType: string; ValueName: ""; ValueData: "PresupuestadorPro.ppto"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\PresupuestadorPro.ppto"; ValueType: string; ValueName: ""; ValueData: "Presupuesto"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\PresupuestadorPro.ppto\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\resources\PptoDocument.ico"
Root: HKA; Subkey: "Software\Classes\PresupuestadorPro.ppto\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir {#AppName}"; Flags: nowait postinstall skipifsilent
