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

echo Starting Nuitka Compilation... Please wait, this WILL take a long time!
echo Command: "%VENV_PYTHON%" -m nuitka --msvc=latest --low-memory --standalone --windows-console-mode=disable --enable-plugin=pyside6 --nofollow-import-to=pymupdf --nofollow-import-to=fitz --include-data-dir=translations=translations --include-data-files=source/style_dark.qss=source/style_dark.qss --include-data-files=source/style_light.qss=source/style_light.qss --include-data-files=source/bookmark.svg=source/bookmark.svg --output-dir=nuitka_build --output-filename=PDFMerger.exe source/main.py
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
  --output-dir=nuitka_build ^
  --output-filename=PDFMerger.exe ^
  source/main.py

REM Check the result
if %errorlevel% neq 0 (
    echo ------------------------------------------------------------
    echo ERROR: Nuitka failed with error code %errorlevel%!
    echo Please check the output above for specific errors.
    echo ------------------------------------------------------------
    pause
    exit /b %errorlevel%
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
