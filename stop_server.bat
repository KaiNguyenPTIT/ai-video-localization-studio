@echo off
chcp 65001 >nul
title Anime Summarizer - Tat Server
echo ======================================================
echo        DANG TAT SERVER ANIME SUMMARIZER (PORT 8000)
echo =====================================================

for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R ":8000 .*LISTENING"') do (
    taskkill /pid %%a /f >nul 2>&1
    if errorlevel 0 (
        echo [OK] Da dung tien trinh PID %%a
    )
)

echo [OK] Server da duoc tat hoan toat.
timeout /t 2 /nobreak >nul
exit
