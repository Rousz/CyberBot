@echo off
rem CyberBot - Demo testi durdurur: bot ve kaydedici duzgunce kapatilir.
rem Cift tikla. Kapanma en fazla 1-2 dakika surer. Veriler silinmez.
rem Sonuc: ekranda ve reports\demo_stop_<UTC zaman>.txt
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title CyberBot - Demo test durdur

if not exist "reports\logs" mkdir "reports\logs"
call "setup\check_docker.bat"
if errorlevel 1 goto :docker_missing

set "MARK=reports\logs\demo_stop_last.txt"
if exist "%MARK%" del /q "%MARK%"

echo.
echo Bot ve kaydedici durduruluyor. Pencereyi kapatma, en fazla 1-2 dakika...
echo.
rem Durdurmadan once oturumlar kaydedilir (saat karsilastirmasi yok). Basarisiz olsa da durdurulur.
docker compose run --rm tools cyberbot.demo_status mark stop
docker compose stop freqtrade recorder
if errorlevel 1 goto :compose_failed

docker compose run --rm tools cyberbot.demo_status stop
set "RC=%ERRORLEVEL%"
if not exist "%MARK%" goto :status_failed

echo.
echo Demo test durdu. Bilgisayar yeniden acilsa da kendiliginden BASLAMAZ.
echo Tekrar baslatmak icin: 10_demo_start.bat   Rapor icin: 12_demo_report.bat
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b %RC%

:docker_missing
call "setup\stamp.bat"
> "reports\demo_stop_error.txt" echo %UTCNOW% UTC - SONUC: HATA - Docker Desktop kurulu degil veya calismiyor.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:compose_failed
call "setup\stamp.bat"
> "reports\demo_stop_error.txt" echo %UTCNOW% UTC - SONUC: HATA - docker compose stop basarisiz.
echo.
echo ==================================================
echo   SONUC: HATA - durdurulamadi
echo ==================================================
echo Docker Desktop - Containers - cyberbot satirindan Stop dugmesiyle de durdurabilirsin.
echo Yukaridaki hata satirlarinin ekran goruntusunu bana getir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:status_failed
call "setup\stamp.bat"
> "reports\demo_stop_error.txt" echo %UTCNOW% UTC - SONUC: HATA - durum kontrolu calismadi, kod %RC%.
echo.
echo ==================================================
echo   SONUC: HATA - durum kontrolu calismadi, kod %RC%
echo ==================================================
echo Bot durmus olabilir ama kapanis kaydi kontrol edilemedi.
echo Yukaridaki hata satirlarinin ekran goruntusunu bana getir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1
