@echo off
setlocal enabledelayedexpansion

echo ===================================
echo   PDF Merger Nuitka Builder
echo ===================================
echo.

REM Define paths
set "VENV_DIR=.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

REM Check if the virtual environment exists
if not exist "%VENV_DIR%" (
    echo ERROR: Virtual environment folder "%VENV_DIR%" not found.
    echo Please create it by running:
    echo   python -m venv %VENV_DIR%
    echo Then activate it and install requirements:
    echo   %VENV_DIR%\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

echo Using Python from: %VENV_PYTHON%
echo.

echo Cleaning previous Nuitka build directories...
if exist "nuitka_build" rd /s /q "nuitka_build"
echo Done cleaning.
echo.

REM Find paths for pymupdf and fitz to bundle them uncompiled
"%VENV_PYTHON%" -c "import pymupdf, os; print(os.path.dirname(pymupdf.__file__))" > pymupdf_dir.txt
set /p PYMUPDF_DIR=<pymupdf_dir.txt
del pymupdf_dir.txt

"%VENV_PYTHON%" -c "import fitz, os; print(os.path.dirname(fitz.__file__))" > fitz_dir.txt
set /p FITZ_DIR=<fitz_dir.txt
del fitz_dir.txt

REM Prepare build metadata
echo Fetching Git commit hash and build date...
set "COMMIT_HASH="
for /f %%i in ('git rev-parse --short HEAD 2^>nul') do set "COMMIT_HASH=%%i"
if "%COMMIT_HASH%"=="" set "COMMIT_HASH=unknown"

set "BUILD_DATE="
for /f %%i in ('%VENV_PYTHON% -c "import datetime; print(datetime.date.today().isoformat())" 2^>nul') do set "BUILD_DATE=%%i"
if "%BUILD_DATE%"=="" set "BUILD_DATE=unknown"

echo Commit Hash: %COMMIT_HASH%
echo Build Date: %BUILD_DATE%
echo.

REM Create backup of version.py
if exist "source\version.py" (
    copy /y "source\version.py" "source\version.py.bak" >nul
)

REM Overwrite version.py with build info
(
echo __version__ = "0.2.0"
echo __build__ = "%COMMIT_HASH%"
echo __build_date__ = "%BUILD_DATE%"
) > "source/version.py"

echo Starting Nuitka Compilation... Please wait, this WILL take a long time!
echo Command: "%VENV_PYTHON%" -m nuitka --msvc=latest --low-memory --standalone --windows-console-mode=disable --enable-plugin=pyside6 --nofollow-import-to=pymupdf --nofollow-import-to=fitz --include-data-dir=translations=translations --include-data-files=source/style_dark.qss=source/style_dark.qss --include-data-files=source/style_light.qss=source/style_light.qss --include-data-files=source/bookmark.svg=source/bookmark.svg --include-data-files=source/bookmark_linked.svg=source/bookmark_linked.svg --include-data-files=source/checkmark.svg=source/checkmark.svg --include-data-files=source/app_icon.png=source/app_icon.png --windows-icon-from-ico=source/app_icon.ico --output-dir=nuitka_build --output-filename=PDFMerger.exe source/main.py
echo ------------------------------------------------------------

REM Run Nuitka
call "%VENV_PYTHON%" -m nuitka ^
  --msvc=latest ^
  --low-memory ^
  --standalone ^
  --windows-console-mode=disable ^
  --enable-plugin=pyside6 ^
  --nofollow-import-to=pymupdf ^
  --nofollow-import-to=fitz ^
  --include-data-dir=translations=translations ^
  --include-data-files=source/style_dark.qss=source/style_dark.qss ^
  --include-data-files=source/style_light.qss=source/style_light.qss ^
  --include-data-files=source/bookmark.svg=source/bookmark.svg ^
  --include-data-files=source/bookmark_linked.svg=source/bookmark_linked.svg ^
  --include-data-files=source/checkmark.svg=source/checkmark.svg ^
  --include-data-files=source/app_icon.png=source/app_icon.png ^
  --windows-icon-from-ico=source/app_icon.ico ^
  --output-dir=nuitka_build ^
  --output-filename=PDFMerger.exe ^
  source/main.py
set "BUILD_ERROR=%errorlevel%"

REM Restore original version.py from backup
if exist "source\version.py.bak" (
    move /y "source\version.py.bak" "source\version.py" >nul
)

REM Check the result
if %BUILD_ERROR% neq 0 (
    echo ------------------------------------------------------------
    echo ERROR: Nuitka failed with error code %BUILD_ERROR%!
    echo Please check the output above for specific errors.
    echo ------------------------------------------------------------
    pause
    exit /b %BUILD_ERROR%
)

echo.
echo Copying bypassed raw modules into the distribution folder...
xcopy /E /I /Y "%PYMUPDF_DIR%" "nuitka_build\main.dist\pymupdf" >nul
xcopy /E /I /Y "%FITZ_DIR%" "nuitka_build\main.dist\fitz" >nul

echo ------------------------------------------------------------
echo Build successful!
echo Executable created in the nuitka_build\main.dist\ directory as PDFMerger.exe.
echo ------------------------------------------------------------
echo.
pause
