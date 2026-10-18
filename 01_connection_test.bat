@echo off
rem CyberBot - Baglanti testi: WEEX + Binance + Telegram (Docker icinde calisir).
rem Cift tikla. Sonuc: ekranda ve reports\connection_test_<UTC zaman>.txt
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title CyberBot - Baglanti testi

if not exist "reports\logs" mkdir "reports\logs"
call "setup\check_docker.bat"
if errorlevel 1 goto :docker_missing

set "MARK=reports\logs\connection_test_last.txt"
if exist "%MARK%" del /q "%MARK%"

echo.
echo Ilk calistirmada CyberBot imaji hazirlanir: Freqtrade 2026.9 indirilir, yaklasik 300 MB, birkac dakika surebilir.
echo Test 1-2 dakika surer. Pencereyi kapatma.
echo.
docker compose run --rm --build conntest cyberbot.connection_test
set "RC=%ERRORLEVEL%"
if not exist "%MARK%" goto :docker_failed
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b %RC%

:docker_missing
call "setup\stamp.bat"
> "reports\connection_test_error.txt" echo %UTCNOW% UTC - SONUC: HATA - Docker Desktop kurulu degil veya calismiyor.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:docker_failed
call "setup\stamp.bat"
> "reports\connection_test_error.txt" echo %UTCNOW% UTC - SONUC: HATA - test calismadi, docker compose kodu %RC%.
echo.
echo ==================================================
echo   SONUC: HATA - test calismadi, Docker kodu %RC%
echo ==================================================
echo Internet baglantisini ve Docker Desktop'i kontrol et.
echo Yukaridaki Ingilizce hata satirlarinin ekran goruntusunu ya da metnini bana getir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1
