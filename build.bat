@echo off
setlocal enabledelayedexpansion

echo ===================================
echo   PDF Merger Executable Builder
echo ===================================
echo.

REM Define paths
set "VENV_DIR=.venv"
set "SPEC_FILE=pdf_merger.spec"
set "VENV_PYINSTALLER=%VENV_DIR%\Scripts\pyinstaller.exe"

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

REM Check if pyinstaller exists in the virtual environment
if not exist "%VENV_PYINSTALLER%" (
    echo ERROR: PyInstaller not found at %VENV_PYINSTALLER%
    echo Please activate the virtual environment and install dependencies:
    echo   %VENV_DIR%\Scripts\activate
    echo   pip install -r requirements.txt
    pause
    exit /b 1
)

REM Check if the spec file exists
if not exist "%SPEC_FILE%" (
    echo ERROR: Spec file "%SPEC_FILE%" not found.
    echo This file is required to build the project correctly with all assets.
    pause
    exit /b 1
)

echo Using PyInstaller from: %VENV_PYINSTALLER%
echo Building using spec: %SPEC_FILE%
echo.

echo Cleaning previous build directories (dist\, build\)...
if exist "dist" rd /s /q "dist"
if exist "build" rd /s /q "build"
echo Done cleaning.
echo.

REM Prepare build metadata
echo Fetching Git commit hash and build date...
set "COMMIT_HASH="
for /f %%i in ('git rev-parse --short HEAD 2^>nul') do set "COMMIT_HASH=%%i"
if "%COMMIT_HASH%"=="" set "COMMIT_HASH=unknown"

set "BUILD_DATE="
for /f %%i in ('%VENV_DIR%\Scripts\python.exe -c "import datetime; print(datetime.date.today().isoformat())" 2^>nul') do set "BUILD_DATE=%%i"
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
) > "source\version.py"

echo Starting PyInstaller... Please wait, this might take a while.
echo Command: "%VENV_PYINSTALLER%" --clean --noconfirm "%SPEC_FILE%"
echo ------------------------------------------------------------

REM Run PyInstaller using the full path from the venv
call "%VENV_PYINSTALLER%" --clean --noconfirm "%SPEC_FILE%"
set "BUILD_ERROR=%errorlevel%"

REM Restore original version.py from backup
if exist "source\version.py.bak" (
    move /y "source\version.py.bak" "source\version.py" >nul
)

REM Check the result
if %BUILD_ERROR% neq 0 (
    echo ------------------------------------------------------------
    echo ERROR: PyInstaller failed with error code %BUILD_ERROR%!
    echo Please check the output above for specific errors.
    echo ------------------------------------------------------------
    pause
    exit /b %BUILD_ERROR%
)

echo ------------------------------------------------------------
echo Build successful!
echo Executable created in the dist\ directory.
echo ------------------------------------------------------------
echo.
pause