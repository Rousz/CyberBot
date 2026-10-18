@echo off
rem CyberBot - Demo testi baslatir: sanal 1000 USDT, WEEX fiyatlari, API anahtari gerekmez.
rem Cift tikla. Bot ve kaydedici arka planda calismaya baslar; bu pencere kapanabilir.
rem Zaten calisiyorlarsa duzgunce durdurulup YENIDEN acilir: guncellemeden (GitHub Desktop Pull)
rem sonra yeni kod/ayar yuklenir, Telegram /stop ve /stopentry sifirlanir.
rem Sonuc: ekranda ve reports\demo_start_<UTC zaman>.txt
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title CyberBot - Demo test baslat

if not exist "reports\logs" mkdir "reports\logs"
call "setup\check_docker.bat"
if errorlevel 1 goto :docker_missing
if not exist ".env" goto :no_env

set "MARK=reports\logs\demo_start_last.txt"
if exist "%MARK%" del /q "%MARK%"

echo.
echo Demo test baslatiliyor. Ilk seferde imaj hazirlanir, birkac dakika surebilir.
echo Bot zaten calisiyorsa duzgunce durdurulup yeniden acilir, en fazla 1-2 dakika.
echo.
rem Saat karsilastirmasi yok: once mevcut oturumlar kaydedilir, sonra YENI oturum aranir.
docker compose run --rm --build tools cyberbot.demo_status mark start
if errorlevel 1 goto :mark_failed
docker compose up -d --build --force-recreate freqtrade recorder
if errorlevel 1 goto :compose_failed

echo.
echo Bot ve kaydedicinin acilmasi kontrol ediliyor, en fazla 2 dakika...
docker compose run --rm tools cyberbot.demo_status start
set "RC=%ERRORLEVEL%"
if not exist "%MARK%" goto :status_failed
if not "%RC%"=="0" goto :start_failed

echo.
echo Demo test ARKA PLANDA calisiyor. Bu pencereyi kapatabilirsin.
echo - Bilgisayar yeniden acilinca Docker Desktop kendiliginden acilir ve bot da otomatik baslar.
echo - Botu Telegram'dan izle: /status /profit /balance /daily /help
echo - Durdurmak icin: 11_demo_stop.bat   Rapor icin: 12_demo_report.bat
echo - Ayrintilar: docs\DEMO_TEST.md
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 0

:start_failed
echo.
echo Bot veya kaydedici duzgun acilmadi. Aciklama ve son log satirlari yukarida.
echo reports klasorundeki en yeni demo_start dosyasini bana getir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:no_env
call "setup\stamp.bat"
> "reports\demo_start_error.txt" echo %UTCNOW% UTC - SONUC: HATA - .env dosyasi yok.
echo.
echo ==================================================
echo   SONUC: HATA - .env dosyasi yok
echo ==================================================
echo Once setup_env.bat dosyasina cift tikla, Telegram bilgilerini yaz ve kaydet.
echo Sonra bu dosyayi tekrar calistir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:mark_failed
call "setup\stamp.bat"
> "reports\demo_start_error.txt" echo %UTCNOW% UTC - SONUC: HATA - baslatma oncesi durum kaydedilemedi, bot baslatilmadi.
echo.
echo ==================================================
echo   SONUC: HATA - bot baslatilmadi
echo ==================================================
echo Imaj hazirlanamadi ya da calisma kaydi okunamadi. Internet baglantisini kontrol et.
echo Yukaridaki hata satirlarinin ekran goruntusunu ya da metnini bana getir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:docker_missing
call "setup\stamp.bat"
> "reports\demo_start_error.txt" echo %UTCNOW% UTC - SONUC: HATA - Docker Desktop kurulu degil veya calismiyor.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:compose_failed
call "setup\stamp.bat"
> "reports\demo_start_error.txt" echo %UTCNOW% UTC - SONUC: HATA - docker compose up basarisiz.
echo.
echo ==================================================
echo   SONUC: HATA - bot baslatilamadi
echo ==================================================
echo Imaj hazirlanamadi ya da Docker hata verdi. Internet baglantisini kontrol et.
echo Yukaridaki Ingilizce hata satirlarinin ekran goruntusunu ya da metnini bana getir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

:status_failed
call "setup\stamp.bat"
> "reports\demo_start_error.txt" echo %UTCNOW% UTC - SONUC: HATA - durum kontrolu calismadi, kod %RC%.
echo.
echo ==================================================
echo   SONUC: HATA - durum kontrolu calismadi, kod %RC%
echo ==================================================
echo Bot yine de calisiyor olabilir: Docker Desktop - Containers - cyberbot satirina bak.
echo Yukaridaki hata satirlarinin ekran goruntusunu bana getir.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1
