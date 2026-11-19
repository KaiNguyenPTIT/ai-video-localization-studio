@echo off
chcp 65001 >nul
title Anime Summarizer Launcher
cd /d "%~dp0"

echo ======================================================
echo          ANIME SUMMARIZER - 1-CLICK LAUNCHER
echo =====================================================

netstat -ano | findstr ":8000 " | findstr /i "LISTENING" >nul 2>&1 && goto server_already_running

echo [*] Server chua chay. Dang khoi dong server...
start "Anime Summarizer Server" /d "%~dp0" cmd /k "venv\Scripts\python.exe -m backend.main"

echo [!] Dang khoi dong server tren cong 8000...
set count=0

:wait_loop
ping 127.0.0.1 -n 2 >nul
set /a count=%count%+1
netstat -ano | findstr ":8000 " | findstr /i "LISTENING" >nul 2>&1 && goto server_ready
if %count% geq 15 goto server_timeout
goto wait_loop

:server_timeout
echo [!] Server khoi dong lau hon du kien, van mo trinh duyet...
goto open_browser

:server_already_running
echo [*] Server da dang chay san!
goto open_browser

:server_ready
echo [OK] Server da san sang!

:open_browser
echo [*] Dang mo trinh duyet http://localhost:8000 ...
start "" "http://localhost:8000"
ping 127.0.0.1 -n 2 >nul
exit
