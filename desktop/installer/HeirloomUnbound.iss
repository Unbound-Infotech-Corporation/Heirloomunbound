; Heirloom Unbound Setup — Inno Setup 6.
; Compile on Windows with Build-HeirloomUnbound-Setup.bat
; Product name must stay Heirloom Unbound.

#define MyAppName "Heirloom Unbound"
#define MyAppPublisher "Unbound Infotech Corporation"
#define MyAppVersion "0.5.1"
#define MyAppExeName "Heirloom.exe"

#ifndef DistDir
  #define DistDir "..\\dist\\Heirloom-ready"
#endif

[Setup]
AppId={{8F3C1A2E-9B70-4E11-A6D2-7E18100B4A2C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://heirloom.unbound
DefaultDirName={autopf}\Heirloom Unbound
DefaultGroupName=Heirloom Unbound
DisableProgramGroupPage=yes
LicenseFile=license.txt
InfoBeforeFile=privacy.txt
OutputDir=..\dist
OutputBaseFilename=HeirloomUnboundSetup
SetupIconFile=
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
UninstallDisplayName=Heirloom Unbound
WizardSizePercent=120,120
DisableWelcomePage=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel1=Welcome to Heirloom Unbound Setup
WelcomeLabel2=This installs Heirloom Unbound on your PC, then downloads the models for the install size you choose.%n%nLocal models stay on this computer. Setup is not a batch file — it is a studio installer.%n%nWindows SmartScreen may warn because this Setup is unsigned. Choose More info, then Run anyway.
FinishedHeadingLabel=Heirloom Unbound is installed
FinishedLabel=Launch Heirloom Unbound to finish any remaining downloads. Engine listeners that are not ready get a coach line — Setup does not abort the whole install.
ClickFinish=Click Finish to close Setup.

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; GroupDescription: "Shortcuts:"
Name: "startwin"; Description: "Start Heirloom Unbound with Windows (this user)"; GroupDescription: "Dedicated PC:"; Flags: unchecked

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs; Excludes: "*.pdb"
Source: "license.txt"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "privacy.txt"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "provision.bat"; DestDir: "{app}\installer"; Flags: ignoreversion
Source: "branding\dedicated.txt"; DestDir: "{localappdata}\Heirloom\branding"; Flags: ignoreversion

[Icons]
Name: "{group}\Heirloom Unbound"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\Heirloom Unbound"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
Name: "{userstartup}\Heirloom Unbound"; Filename: "{app}\{#MyAppExeName}"; Tasks: startwin

[Run]
Filename: "{app}\installer\provision.bat"; Parameters: """{code:GetProfile}"" ""{code:GetVault}"" ""{code:GetConsent}"" ""{app}"""; StatusMsg: "Writing Heirloom Unbound install_profile and starting provision…"; Flags: runhidden waituntilterminated
Filename: "{app}\{#MyAppExeName}"; Description: "Launch Heirloom Unbound"; Flags: nowait postinstall skipifsilent skipifdoesntexist

[Code]
var
  SizePage: TInputOptionWizardPage;
  DedPage: TInputQueryWizardPage;
  DedConsent, DedPower, DedWarm, DedListen, DedBrand: TNewCheckBox;
  ProfileId: String;

procedure InitializeWizard;
begin
  ProfileId := 'medium';

  SizePage := CreateInputOptionPage(wpLicense,
    'Choose install size',
    'How much of this PC should Heirloom Unbound use?',
    'Four sizes. Downloads resume if they pause. Engine failure coaches and continues — it does not abort Setup unless the app itself cannot be written. Never Pinokio.',
    True, False);
  SizePage.Add('Small · 5–12 GB · Whisper + Piper + lite vault. Twin/TTS/avatar stay cloud Auto. No GPU required.');
  SizePage.Add('Medium · 40–70 GB · Small + Ollama llama3.1 + one voice-clone path (Qwen3-TTS 0.6B or Voicebox).');
  SizePage.Add('Large · 100–160 GB · Whisper large-v3, stronger twin + vision, Voicebox AND Qwen3-TTS 1.7B, LatentSync.');
  SizePage.Add('Dedicated PC · 200 GB+ · Everything in Large. This PC exists for Heirloom Unbound.');
  SizePage.Values[1] := True;

  DedPage := CreateInputQueryPage(wpSelectDir,
    'Dedicated PC',
    'This PC exists for Heirloom Unbound',
    'Recommend a second disk for the vault. Start-with-Windows uses this user. High-performance power plan is applied only if you consent — Setup will not silently fight IT policy.');
  DedPage.Add('Vault / data drive:', False);
  DedPage.Values[0] := ExpandConstant('{userdocs}\HeirloomVault');

  DedConsent := TNewCheckBox.Create(DedPage);
  DedConsent.Parent := DedPage.Surface;
  DedConsent.Caption := 'This PC exists for Heirloom Unbound';
  DedConsent.Checked := True;
  DedConsent.Top := DedPage.SurfaceHeight - ScaleY(110);
  DedConsent.Width := DedPage.SurfaceWidth;

  DedPower := TNewCheckBox.Create(DedPage);
  DedPower.Parent := DedPage.Surface;
  DedPower.Caption := 'Apply high-performance power plan (I consent)';
  DedPower.Checked := False;
  DedPower.Top := DedConsent.Top + ScaleY(22);
  DedPower.Width := DedPage.SurfaceWidth;

  DedWarm := TNewCheckBox.Create(DedPage);
  DedWarm.Parent := DedPage.Surface;
  DedWarm.Caption := 'Warm Ollama, Voicebox, Qwen3-TTS, LatentSync listeners';
  DedWarm.Checked := True;
  DedWarm.Top := DedPower.Top + ScaleY(22);
  DedWarm.Width := DedPage.SurfaceWidth;

  DedListen := TNewCheckBox.Create(DedPage);
  DedListen.Parent := DedPage.Surface;
  DedListen.Caption := 'Standing routines + live room listen toward on (still togglable)';
  DedListen.Checked := True;
  DedListen.Top := DedWarm.Top + ScaleY(22);
  DedListen.Width := DedPage.SurfaceWidth;

  DedBrand := TNewCheckBox.Create(DedPage);
  DedBrand.Parent := DedPage.Surface;
  DedBrand.Caption := 'Optional mark: Heirloom Unbound · Dedicated';
  DedBrand.Checked := False;
  DedBrand.Top := DedListen.Top + ScaleY(22);
  DedBrand.Width := DedPage.SurfaceWidth;
end;

function SelectedProfile: String;
begin
  if SizePage.Values[0] then Result := 'small'
  else if SizePage.Values[1] then Result := 'medium'
  else if SizePage.Values[2] then Result := 'large'
  else if SizePage.Values[3] then Result := 'dedicated'
  else Result := 'medium';
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if PageID = DedPage.ID then
    Result := SelectedProfile() <> 'dedicated';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = SizePage.ID then
    ProfileId := SelectedProfile();
  if CurPageID = DedPage.ID then
  begin
    if not DedConsent.Checked then
    begin
      MsgBox('Dedicated PC needs the consent that this computer exists for Heirloom Unbound.', mbInformation, MB_OK);
      Result := False;
    end;
  end;
end;

function GetProfile(Param: String): String;
begin
  Result := SelectedProfile();
end;

function GetVault(Param: String): String;
begin
  if SelectedProfile() = 'dedicated' then
    Result := DedPage.Values[0]
  else
    Result := ExpandConstant('{userdocs}\HeirloomVault');
end;

function GetConsent(Param: String): String;
begin
  if (SelectedProfile() = 'dedicated') and DedConsent.Checked then
    Result := 'yes'
  else
    Result := 'no';
end;

function UpdateReadyMemo(Space, NewLine, MemoUserInfo, MemoDir, MemoType, MemoComponents, MemoGroup, MemoTasks: String): String;
var
  SizeNote: String;
begin
  case SelectedProfile() of
    'small': SizeNote := 'Small · 5–12 GB · CPU Whisper, cloud Auto twin';
    'medium': SizeNote := 'Medium · 40–70 GB · local twin + one clone path';
    'large': SizeNote := 'Large · 100–160 GB · full local stack';
    'dedicated': SizeNote := 'Dedicated PC · 200 GB+ · this machine exists for Heirloom Unbound';
  else
    SizeNote := SelectedProfile();
  end;
  Result := 'Heirloom Unbound Setup' + NewLine + NewLine +
    'Install size: ' + SizeNote + NewLine +
    MemoDir + NewLine +
    'Local models stay on this PC. Engine failure coaches and continues.' + NewLine;
end;
