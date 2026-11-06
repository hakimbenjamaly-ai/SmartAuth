@echo off
REM ============================================================
REM  SmartAuth - build the Windows installer (run once on the build machine)
REM  Build machine needs: Python 3.11+ (64-bit), Tesseract 5, Inno Setup 6, internet.
REM  End users need nothing: the installer contains everything and works offline.
REM  Optional:  set WITH_HANDWRITING=1   and   set ARABIC_HTR_MODEL=<hf-id or folder>
REM ============================================================
setlocal
cd /d "%~dp0\.."
set PYTHONUTF8=1

echo [1/7] Python environment...
if not exist .venv python -m venv .venv || goto :err
call .venv\Scripts\activate.bat || goto :err
python -m pip install --upgrade pip || goto :err
pip install -r requirements.txt || goto :err

if "%WITH_HANDWRITING%"=="1" goto :hw
echo [2/7] Handwriting model skipped (set WITH_HANDWRITING=1 to include it)
goto :tess
:hw
echo [2/7] Handwriting model...
pip install -r requirements-handwriting.txt || goto :err
python tools\download_models.py --handwriting-eng microsoft/trocr-base-handwritten || goto :err
if not "%ARABIC_HTR_MODEL%"=="" python tools\download_models.py --handwriting-ara "%ARABIC_HTR_MODEL%" || goto :err

:tess
echo [3/7] Tesseract OCR...
if exist tesseract\tesseract.exe goto :tessdata
if not exist "C:\Program Files\Tesseract-OCR\tesseract.exe" goto :notess
xcopy /E /I /Y /Q "C:\Program Files\Tesseract-OCR" tesseract >nul || goto :err

:tessdata
echo [4/7] Arabic + English language data (tessdata_best)...
python tools\download_models.py --tessdata || goto :err

echo [5/7] Automated tests...
python -m pytest -q tests
if errorlevel 1 (
  echo pytest exit code: %errorlevel%
  goto :err
)

echo [6/7] PyInstaller...
pyinstaller --noconfirm --clean installer\smart_auth.spec || goto :err

echo [7/7] Self-test of the built program...
dist\SmartAuth\SmartAuth.exe --selftest --log=dist\selftest.log
if errorlevel 1 (
  type dist\selftest.log
  goto :err
)
type dist\selftest.log

set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% goto :noiscc
if "%APP_VERSION%"=="" set APP_VERSION=1.0.0
%ISCC% /DAppVersion=%APP_VERSION% installer\SmartAuth.iss || goto :err
echo.
echo SUCCESS: dist_installer\SmartAuth_Setup_%APP_VERSION%.exe
exit /b 0

:noiscc
echo Program built in dist\SmartAuth. Install Inno Setup 6 to produce the setup file.
exit /b 0

:notess
echo ERROR: install Tesseract 5 (UB Mannheim build) or put its folder here as "tesseract".
goto :err

:err
echo.
echo BUILD FAILED - see messages above.
exit /b 1
