@echo off
chcp 65001 >nul
title Anime Summarizer Tool - AI Auto Pipeline
color 0B
set MANAGED_BY_RUN_BAT=1

echo =======================================================================
echo          ANIME SUMMARIZER TOOL - AUTO SETUP v2
echo =======================================================================
echo.

:: 1. KIEM TRA PYTHON
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [LOI] May tinh cua ban chua cai dat Python hoac chua tick 'Add Python to PATH'!
    echo -^> Vui long tai va cai dat Python tai: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

:: 2. KIEM TRA FFMPEG
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [CANH BAO] May ban chua co FFmpeg trong PATH!
    echo Cai nhanh bang lenh PowerShell:  winget install Gyan.FFmpeg
    echo Neu da cai roi thi co the bo qua thong bao nay
    echo.
)

:: 3. KHOI TAO VIRTUAL ENVIRONMENT & CAI THU VIEN
if not exist "venv" (
    echo [*] Dang tao Virtual Environment ... venv
    python -m venv venv
)

echo [*] Dang cai dat thu vien trong moi truong ao...
venv\Scripts\pip.exe install -q -r requirements.txt

:: 4. KIEM TRA GEMINI API KEY
if not exist ".env" (
    echo.
    echo =======================================================================
    echo [!] CHUA CO GEMINI API KEY
    echo Lay API Key mien phi tai:  https://aistudio.google.com/app/apikey
    echo =======================================================================
    set /p API_KEY="^>^> Vui long dan Gemini API Key vao day: "
    echo GEMINI_API_KEY=%API_KEY%> .env
    echo GEMINI_MODEL=gemini-2.5-flash>> .env
    echo [*] Da luu API Key vao file .env!
)

:: 5. TAT CONG 8000 NEU DA CHAY
echo.
echo =======================================================================
echo  [*] DANG TAT CAC TIEN TRINH PYTHON CHAY TREN CONG 8000
echo =======================================================================
echo.

for /f "tokens=5" %%a in ('netstat -ano ^| find ":8000 " ^| find "LISTENING"') do (
    taskkill /pid %%a /f >nul 2>&1
    if errorlevel 0 (
        echo     [OK] Tien trinh %%a da bi dung
    )
)

timeout /t 2 /nobreak >nul

:: 6. KHOI CHAY SERVER & MO TRINH DUYET
echo.
echo =======================================================================
echo  DANG KHOI DONG ANIME SUMMARIZER WEB SERVER TAI http://localhost:8000
echo =======================================================================
echo.

start "" "http://localhost:8000"
timeout /t 3 /nobreak >nul
:server_loop
venv\Scripts\python.exe -m backend.main
if errorlevel 1 (
    echo.
    echo [DUNG] Server thoat voi loi (exit code %errorlevel%) - khong tu khoi dong lai.
    pause
    exit /b %errorlevel%
)
echo.
echo [RESTART] Server yeu cau khoi dong lai (nut Restart tu trang admin)...
timeout /t 3 /nobreak >nul
goto server_loop
