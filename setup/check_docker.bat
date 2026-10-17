@echo off
rem Docker Desktop kurulu ve calisiyor mu? Degilse aciklama yazar ve errorlevel 1 doner.
where docker >nul 2>&1
if errorlevel 1 goto :not_installed
docker info >nul 2>&1
if errorlevel 1 goto :not_running
exit /b 0

:not_installed
echo.
echo ==================================================
echo   SONUC: HATA - Docker kurulu degil
echo ==================================================
echo Kurulum: docs\SETUP_WINDOWS.md dosyasindaki Adim 5.
exit /b 1

:not_running
echo.
echo ==================================================
echo   SONUC: HATA - Docker Desktop calismiyor
echo ==================================================
echo Docker Desktop'i ac, sol altta "Engine running" yazisini bekle,
echo sonra bu dosyayi tekrar cift tikla.
exit /b 1
