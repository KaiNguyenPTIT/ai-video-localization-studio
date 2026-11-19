@echo off
setlocal EnableExtensions
chcp 65001 >nul
title Setup shared data folder

rem ============================================================
rem  Dat thu muc du lieu (data/) ra NGOAI thu muc phien ban.
rem  Sau khi chay 1 lan: nang cap len ban moi chi can thay code,
rem  du lieu (DB, video, cache, Chrome profile, .env keys...) giu nguyen.
rem
rem  Cach dung:
rem    setup_shared_data.bat                  -> %LOCALAPPDATA%\AnimeSummarizer\data
rem    setup_shared_data.bat D:\AnimeData     -> thu muc chi dinh
rem ============================================================

set "SRC=%~dp0data"
set "TARGET=%~1"
if "%TARGET%"=="" set "TARGET=%LOCALAPPDATA%\AnimeSummarizer\data"

echo.
echo  Nguon : "%SRC%"
echo  Dich  : "%TARGET%"
echo.
echo  CANH BAO: hay TAT server (stop_server.bat) va dong cua so Chrome automation (neu co).
choice /c YN /n /m "  Tiep tuc? [Y/N] "
if errorlevel 2 exit /b 0

echo.
if not exist "%TARGET%" mkdir "%TARGET%" >nul 2>&1
if not exist "%TARGET%" (
    echo  [LOI] Khong tao duoc thu muc dich.
    pause
    exit /b 1
)

rem Chia se luon .env (API key...) neu thu muc dung chung chua co
if exist "%~dp0.env" if not exist "%TARGET%\.env" (
    copy /y "%~dp0.env" "%TARGET%\.env" >nul
    echo  [i] Da sao .env sang thu muc dung chung.
)

rem Neu data hien tai la junction/symlink thi khong di chuyen (tranh copy vong)
fsutil reparsepoint query "%SRC%" >nul 2>&1
if not errorlevel 1 (
    echo  [1/3] data/ la lien ket - bo qua buoc di chuyen.
    goto setenv
)

if exist "%SRC%" (
    echo  [1/3] Dang di chuyen du lieu cu sang thu muc dung chung...
    robocopy "%SRC%" "%TARGET%" /E /MOVE /R:1 /W:1 /NFL /NDL /NJH /NJS >nul
    if errorlevel 8 (
        echo  [LOI] robocopy that bai. Kiem tra dung luong o dia / quyen truy cap.
        pause
        exit /b 1
    )
    rmdir "%SRC%" >nul 2>&1
) else (
    echo  [1/3] Khong co data/ trong ban nay - bo qua buoc di chuyen.
)

:setenv
echo  [2/3] Dat bien moi truong nguoi dung ANIME_DATA_DIR...
setx ANIME_DATA_DIR "%TARGET%" >nul
if errorlevel 1 (
    echo  [LOI] setx that bai.
    pause
    exit /b 1
)

echo  [3/3] Hoan tat.
echo.
echo  Du lieu dung chung : "%TARGET%"
echo  Bien moi truong   : ANIME_DATA_DIR (chi ap dung cho cua so MOI)
echo.
echo  Buoc tiep theo:
echo    1. Dong cua so nay, mo lai terminal / chay run.bat
echo    2. Voi ban moi: copy code, CHAY LAI file nay 1 lan (khong copy data)
echo.
pause
