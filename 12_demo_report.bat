@echo off
rem CyberBot - Demo test raporu: islemler, kar/zarar, calisma suresi, kesintiler.
rem Cift tikla. Bot calisirken de kullanilabilir, botu etkilemez.
rem Sonuc: ekranda ve reports\demo_report_<UTC zaman>.txt
rem Sadece son N gun icin: komut satirindan  12_demo_report.bat --days 7
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title CyberBot - Demo test raporu

if not exist "reports\logs" mkdir "reports\logs"
call "setup\check_docker.bat"
if errorlevel 1 goto :docker_missing

set "MARK=reports\logs\demo_report_last.txt"
if exist "%MARK%" del /q "%MARK%"

echo.
echo Rapor hazirlaniyor...
echo.
docker compose run --rm --build tools cyberbot.demo_report %*
set "RC=%ERRORLEVEL%"
if not exist "%MARK%" goto :docker_failed
echo.
echo Rapor dosyasini reports klasorunden GitHub Desktop ile bana gonder.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b %RC%

:docker_missing
call "setup\stamp.bat"
> "reports\demo_report_error.txt" echo %UTCNOW% UTC - SONUC: HATA - Docker Desktop kurulu degil veya calismiyor.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:docker_failed
call "setup\stamp.bat"
> "reports\demo_report_error.txt" echo %UTCNOW% UTC - SONUC: HATA - rapor calismadi, docker compose kodu %RC%.
echo.
echo ==================================================
echo   SONUC: HATA - rapor calismadi, Docker kodu %RC%
echo ==================================================
echo Yukaridaki Ingilizce hata satirlarinin ekran goruntusunu ya da metnini bana getir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1
