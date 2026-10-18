@echo off
rem CyberBot - WEEX ve Binance davranis probu, Faz 1 - Docker icinde calisir.
rem Cift tikla. Sonuc: ekranda ve reports\weex_probe_<UTC zaman>.txt
rem Sadece herkese acik piyasa verisi okunur; API anahtari kullanilmaz, emir gonderilmez.
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title CyberBot - WEEX probu

if not exist "reports\logs" mkdir "reports\logs"
call "setup\check_docker.bat"
if errorlevel 1 goto :docker_missing

set "MARK=reports\logs\weex_probe_last.txt"
if exist "%MARK%" del /q "%MARK%"

echo.
echo Gerekirse CyberBot imaji once hazirlanir, birkac dakika surebilir.
echo Prob 5-10 dakika surer: Binance verisinin yayin gecikmesi ve likidasyon akisi beklenir.
echo Pencereyi kapatma.
echo.
docker compose run --rm --build tools cyberbot.weex_probe
set "RC=%ERRORLEVEL%"
if not exist "%MARK%" goto :docker_failed
echo.
echo Sonuc dosyasini reports klasorunden GitHub Desktop ile bana gonder.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b %RC%

:docker_missing
call "setup\stamp.bat"
> "reports\weex_probe_error.txt" echo %UTCNOW% UTC - SONUC: HATA - Docker Desktop kurulu degil veya calismiyor.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:docker_failed
call "setup\stamp.bat"
> "reports\weex_probe_error.txt" echo %UTCNOW% UTC - SONUC: HATA - prob calismadi, docker compose kodu %RC%.
echo.
echo ==================================================
echo   SONUC: HATA - prob calismadi, Docker kodu %RC%
echo ==================================================
echo Internet baglantisini ve Docker Desktop'i kontrol et.
echo Yukaridaki Ingilizce hata satirlarinin ekran goruntusunu ya da metnini bana getir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1
