; Inno Setup script for OSINTBox
; Produces an installer registered in Windows Apps & Features.

#define MyAppName "OSINTBox"
#ifndef MyAppVersion
	#define MyAppVersion "1.0.0"
#endif
#ifndef MyOutputSuffix
	#define MyOutputSuffix ""
#endif
#define MyAppPublisher "OSINTBox"
#define MyAppExeName "OSINTBox.exe"
#define MyAppId "8B1C6D2E-4F0A-4C9B-9E3D-7A5F2B6C8D14"

[Setup]
AppId={{{#MyAppId}}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\OSINTBox
DefaultGroupName=OSINTBox
DisableProgramGroupPage=yes
OutputDir=installer_output
OutputBaseFilename=OSINTBoxSetup{#MyOutputSuffix}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=pictures\osint_box.ico
SetupLogging=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Creer un raccourci sur le bureau"; GroupDescription: "Raccourcis:"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\osintbox-rs.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "osintbox.local.yaml.example"; DestDir: "{app}"; Flags: ignoreversion
Source: "requirements-tools.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\OSINTBox"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\OSINTBox"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Lancer OSINTBox"; Flags: nowait postinstall skipifsilent

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    MsgBox('OSINTBox orchestre 4 outils externes (Sherlock, Maigret, Holehe, theHarvester) via ' +
      'sous-processus -- ils ne sont PAS inclus dans cet installeur.' + #13#10 + #13#10 +
      'Pour les installer (ne PAS creer le venv dans ce dossier -- Program Files n''est pas ' +
      'ecrivable sans elevation) : ouvrez un terminal, "cd %LOCALAPPDATA%\OSINTBox", ' +
      '"python -m venv tools", "tools\Scripts\activate", puis depuis ' + ExpandConstant('{app}') +
      ' : "pip install -r requirements-tools.txt". Ajoutez ensuite ' +
      '%LOCALAPPDATA%\OSINTBox\tools\Scripts au PATH systeme, ou lancez toujours OSINTBox ' +
      'depuis un terminal ou ce venv est active.',
      mbInformation, MB_OK);
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
  begin
    if MsgBox('Supprimer aussi les donnees utilisateur (resultats de recherches, cle API, ' +
      'runs bruts) ?' + #13#10 + #13#10 + 'Cette action est irreversible.',
      mbConfirmation, MB_YESNO) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\OSINTBox'), True, True, True);
    end;
  end;
end;
