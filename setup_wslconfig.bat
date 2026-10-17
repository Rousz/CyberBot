@echo off
rem CyberBot - Docker/WSL2'nin RAM ve islemci kullanimini sinirlar.
rem setup\wslconfig.txt dosyasini %USERPROFILE%\.wslconfig olarak kopyalar.
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title CyberBot - Docker RAM siniri
if not exist "reports" mkdir "reports"
call "setup\stamp.bat"
set "TARGET=%USERPROFILE%\.wslconfig"

echo Bu islem Docker/WSL'in kullanabilecegi RAM'i 6 GB, islemciyi 4 cekirdek ile sinirlar.
echo Hedef dosya: %TARGET%
echo.
if not exist "%TARGET%" goto :write

echo Bu bilgisayarda zaten bir .wslconfig var:
echo --------------------------------------------------
type "%TARGET%"
echo --------------------------------------------------
choice /C EH /M "Yedeklenip uzerine yazilsin mi? E=Evet H=Hayir"
if errorlevel 2 goto :skipped
copy /Y "%TARGET%" "%TARGET%.bak" >nul
echo Eski dosya yedeklendi: %TARGET%.bak

:write
copy /Y "setup\wslconfig.txt" "%TARGET%" >nul
if errorlevel 1 goto :failed
echo Yazildi: %TARGET%
>> "reports\setup_history.txt" echo %UTCNOW% UTC - setup_wslconfig: BASARILI - .wslconfig yazildi
echo.
echo Ayarin gecerli olmasi icin WSL yeniden baslatilmali.
echo Once Docker Desktop'i kapat: saat yanindaki balina simgesine sag tikla, Quit Docker Desktop.
choice /C EH /M "Docker Desktop kapali mi, simdi wsl --shutdown calistirilsin mi? E=Evet H=Hayir"
if errorlevel 2 goto :later
wsl --shutdown
echo WSL kapatildi. Simdi Docker Desktop'i tekrar ac.
goto :done

:later
echo Tamam. Bilgisayari yeniden baslattiginda da ayar gecerli olur.
goto :done

:skipped
>> "reports\setup_history.txt" echo %UTCNOW% UTC - setup_wslconfig: ATLANDI - mevcut .wslconfig korundu
echo Degisiklik yapilmadi.
echo.
echo ==================================================
echo   SONUC: BASARILI - mevcut ayar korundu
echo ==================================================
pause
exit /b 0

:done
echo.
echo ==================================================
echo   SONUC: BASARILI - .wslconfig yazildi
echo ==================================================
pause
exit /b 0

:failed
>> "reports\setup_history.txt" echo %UTCNOW% UTC - setup_wslconfig: HATA - .wslconfig yazilamadi
echo ==================================================
echo   SONUC: HATA - .wslconfig yazilamadi
echo ==================================================
pause
exit /b 1
