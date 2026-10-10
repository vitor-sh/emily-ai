#ifndef AppVersion
  #error Compile com /DAppVersion=1.0.0
#endif

[Setup]
AppId={{4E014C07-9A7B-4A79-962A-4FEE0D4D1F09}
AppName=Emily
AppVersion={#AppVersion}
AppPublisher=Emily
AppCopyright=Emily
DefaultDirName={localappdata}\Programs\Emily
DefaultGroupName=Emily
OutputDir=..\dist\installer
OutputBaseFilename=Emily-Setup-{#AppVersion}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2
SolidCompression=yes
WizardStyle=modern dark polar includetitlebar
WizardImageFile=emily-welcome.png
WizardSmallImageFile=emily-app-icon.png
WizardImageBackColor=#151217
WizardSmallImageBackColor=#151217
SetupIconFile=emily.ico
UninstallDisplayName=Emily
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\Emily.exe

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
brazilianportuguese.WelcomeLabel1=Bem-vindo à Emily
brazilianportuguese.WelcomeLabel2=Sua assistente está pronta para fazer parte deste PC.%n%nO instalador vai preparar a interface, o gateway do Android e os atalhos. Suas conversas e preferências ficam salvas entre as atualizações.
brazilianportuguese.FinishedHeadingLabel=Emily pronta para conversar
brazilianportuguese.FinishedLabel=Instalação concluída. Abra a Emily para começar.

[InstallDelete]
; Os dados pessoais ficam em %LOCALAPPDATA%\Emily, fora da pasta do app.
; Remove somente módulos antigos que não existem mais na versão nova.
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "..\dist\Emily\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\windows-build\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{group}\Emily"; Filename: "{app}\Emily.exe"
Name: "{autodesktop}\Emily"; Filename: "{app}\Emily.exe"; Tasks: desktopicon
Name: "{userstartup}\Emily Gateway"; Filename: "{app}\Emily.exe"; Parameters: "--gateway"

[Tasks]
Name: desktopicon; Description: "Criar atalho na área de trabalho"; GroupDescription: "Atalhos:"

[Run]
Filename: "{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; Parameters: "/silent /install"; StatusMsg: "Preparando a interface da Emily..."; Flags: runhidden
Filename: "{app}\Emily.exe"; Parameters: "--gateway"; Flags: nowait
Filename: "{app}\Emily.exe"; Description: "Abrir Emily"; Flags: postinstall nowait skipifsilent
Filename: "{app}\Emily.exe"; Flags: nowait skipifnotsilent

[Code]
var
  InstalacaoExistente: Boolean;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpReady then
  begin
    InstalacaoExistente := FileExists(ExpandConstant('{app}\Emily.exe'));
    if InstalacaoExistente then
      WizardForm.NextButton.Caption := 'Instalar por cima'
    else
      WizardForm.NextButton.Caption := SetupMessage(msgButtonInstall);
  end;
end;

procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
begin
  if MaxProgress = 0 then
    Exit;
  if CurProgress * 100 < MaxProgress * 25 then
    WizardForm.StatusLabel.Caption := 'Preparando a Emily...'
  else if CurProgress * 100 < MaxProgress * 75 then
    WizardForm.StatusLabel.Caption := 'Instalando os recursos da Emily...'
  else
    WizardForm.StatusLabel.Caption := 'Finalizando os atalhos e integrações...';
end;
