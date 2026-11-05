; Inno Setup script — ملف تثبيت منظومة التصديقات والأرشفة الذكية
; البناء: iscc installer\SmartAuth.iss  (بعد تشغيل PyInstaller)

#define AppName "منظومة التصديقات والأرشفة الذكية"
#define AppVersion "1.0.0"

[Setup]
AppId={{6C1F2B4E-7A1D-4C8E-9F33-5B1A0E7D2C91}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Smart Authentication System
DefaultDirName={autopf}\SmartAuth
DefaultGroupName={#AppName}
OutputDir=..\dist_installer
OutputBaseFilename=SmartAuth_Setup_{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
PrivilegesRequired=admin
WizardStyle=modern
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\SmartAuth.exe

[Languages]
; ملف الترجمة العربية لمعالج التثبيت (Arabic.isl) غير مضمن رسمياً في Inno Setup:
; نزّله من صفحة الترجمات غير الرسمية في موقع Inno Setup وضعه بجانب هذا الملف.
#if FileExists(AddBackslash(SourcePath) + "Arabic.isl")
Name: "arabic"; MessagesFile: "Arabic.isl"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "إنشاء اختصار على سطح المكتب"; GroupDescription: "اختصارات:"

[Dirs]
; مجلد البيانات المشترك (قاعدة البيانات والأرشيف) مع صلاحية كتابة للمستخدمين
Name: "{commonappdata}\SmartAuth"; Permissions: users-modify

[Files]
Source: "..\dist\SmartAuth\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\SmartAuth.exe"
Name: "{group}\إلغاء التثبيت"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\SmartAuth.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SmartAuth.exe"; Description: "تشغيل البرنامج الآن"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; لا تُحذف البيانات (قاعدة البيانات والأرشيف) عند إلغاء التثبيت حفاظاً عليها
Type: filesandordirs; Name: "{app}"
