@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM build.bat — Offline Invoice build script (PySide6)
REM Run from the project root folder:  build.bat
REM ─────────────────────────────────────────────────────────────────────────────

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║         Offline Invoice — Build Script               ║
echo ╚══════════════════════════════════════════════════════╝
echo.

REM ── 1. Check Python 3.11 ─────────────────────────────────────────────────────
py -3.11 --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 3.11 not found.
    echo         Download: https://www.python.org/downloads/release/python-3119/
    pause & exit /b 1
)
echo [OK] Python 3.11 found

REM ── 2. Set fontconfig env vars ───────────────────────────────────────────────
REM      WeasyPrint needs these during PyInstaller analysis phase
set FONTCONFIG_PATH=C:\Program Files\GTK3-Runtime Win64\etc\fonts
set FONTCONFIG_FILE=C:\Program Files\GTK3-Runtime Win64\etc\fonts\fonts.conf
echo [OK] Fontconfig env vars set

REM ── 3. Check required packages ───────────────────────────────────────────────
echo [..] Checking dependencies...

py -3.11 -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [..] Installing PyInstaller...
    py -3.11 -m pip install pyinstaller
)

py -3.11 -m pip show PySide6 >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PySide6 not installed.
    echo         Run: py -3.11 -m pip install PySide6
    pause & exit /b 1
)

py -3.11 -m pip show weasyprint >nul 2>&1
if errorlevel 1 (
    echo [ERROR] weasyprint not installed.
    echo         Run: py -3.11 -m pip install weasyprint
    pause & exit /b 1
)

py -3.11 -m pip show qrcode >nul 2>&1
if errorlevel 1 (
    echo [..] Installing qrcode...
    py -3.11 -m pip install "qrcode[pil]"
)

py -3.11 -m pip show pdf2image >nul 2>&1
if errorlevel 1 (
    echo [..] Installing pdf2image...
    py -3.11 -m pip install pdf2image
)

echo [OK] Dependencies OK

REM ── 4. Clean previous build ───────────────────────────────────────────────────
echo [..] Cleaning previous build...
if exist build\offline_invoice  rmdir /s /q build\offline_invoice
if exist dist\OfflineInvoice    rmdir /s /q dist\OfflineInvoice
echo [OK] Clean done

REM ── 5. Run PyInstaller ───────────────────────────────────────────────────────
echo [..] Running PyInstaller...
echo.
py -3.11 -m PyInstaller offlineinvoice.spec --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] PyInstaller failed. Check the output above.
    pause & exit /b 1
)

REM ── 6. Verify output ─────────────────────────────────────────────────────────
if not exist "dist\OfflineInvoice\OfflineInvoice.exe" (
    echo [ERROR] OfflineInvoice.exe not found in dist\OfflineInvoice\
    pause & exit /b 1
)

echo.
echo ╔══════════════════════════════════════════════════════╗
echo ║              BUILD SUCCESSFUL!                       ║
echo ╠══════════════════════════════════════════════════════╣
echo ║  Output: dist\OfflineInvoice\OfflineInvoice.exe      ║
echo ║                                                      ║
echo ║  Before distributing:                                ║
echo ║  1. Test on a clean machine (no Python installed)    ║
echo ║  2. Verify all 5 templates render correctly          ║
echo ║  3. Verify QR codes generate with a payment link     ║
echo ║  4. Test license activation with a real key          ║
echo ║  5. Check live preview works (requires Poppler)      ║
echo ╚══════════════════════════════════════════════════════╝
echo.

REM ── 7. Open output folder ────────────────────────────────────────────────────
explorer dist\OfflineInvoice
pause