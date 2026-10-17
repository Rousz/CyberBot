@echo off
rem CyberBot - Hizli erisim kontrolu. Docker GEREKMEZ (Windows'un kendi curl.exe'si kullanilir).
rem Cift tikla. Sonuc: ekranda ve reports\quick_check_latest.txt
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title CyberBot - Hizli erisim kontrolu

if not exist "reports" mkdir "reports"
set "OUT=reports\quick_check_latest.txt"
set /a FAILS=0
set /a WARNS=0

where curl.exe >nul 2>&1
if errorlevel 1 goto :no_curl
call "setup\stamp.bat"

> "%OUT%" echo CyberBot - Hizli erisim kontrolu - curl ile, Docker'siz
>> "%OUT%" echo Zaman: %UTCNOW% UTC - Istanbul %ISTNOW%
>> "%OUT%" echo.

echo.
echo  CyberBot hizli erisim kontrolu
echo  Zaman: %UTCNOW% UTC  /  Istanbul %ISTNOW%
echo  Sadece herkese acik adreslere baglanilir, hicbir bilgi gonderilmez.
echo.

call :check "WEEX web sitesi"           "https://www.weex.com/"                              0
call :check "WEEX vadeli REST API"      "https://api-contract.weex.com/capi/v3/market/time"  1
call :check "WEEX spot REST API"        "https://api-spot.weex.com/api/v3/time"              0
call :check "Binance vadeli REST API"   "https://fapi.binance.com/fapi/v1/time"              1
call :check "Binance veri arsivi"       "https://data.binance.vision/"                       0
call :check "Telegram API"              "https://api.telegram.org/"                          0
call :check "Docker Hub - imaj indirme" "https://registry-1.docker.io/v2/"                   0

set "RESULT=BASARILI"
if %WARNS% GTR 0 set "RESULT=BASARILI - uyarilarla"
if %FAILS% GTR 0 set "RESULT=HATA"

echo.
echo ==================================================
echo   SONUC: %RESULT%
echo   hata: %FAILS%   uyari: %WARNS%
echo ==================================================
>> "%OUT%" echo.
>> "%OUT%" echo SONUC: %RESULT% - hata %FAILS%, uyari %WARNS%
echo Ozet dosyasi: %OUT%
echo.
if %FAILS% GTR 0 goto :fail_hint
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 0

:fail_hint
echo HATA olan satir varsa: tarayicidan https://www.weex.com adresini acmayi dene
echo ve reports\quick_check_latest.txt dosyasini bana getir. VPN veya proxy KULLANMA.
echo.
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 1

rem --- tek adres kontrolu: call :check "isim" "adres" kritik(1/0) ---
:check
set "NAME=%~1"
set "URL=%~2"
set "CRIT=%~3"
set "CODE=000"
set "SECS=-"
for /f "tokens=1,2" %%a in ('curl.exe -s -o NUL --ssl-no-revoke -A "CyberBot-quick-check" --max-time 15 -w "%%{http_code} %%{time_total}" "%URL%" 2^>nul') do (
  set "CODE=%%a"
  set "SECS=%%b"
)
set "STATUS=OK"
set "NOTE=ulasildi"
if "!CODE!"=="000" (set "STATUS=HATA" & set "NOTE=baglanti kurulamadi")
if "!CODE!"=="451" (set "STATUS=HATA" & set "NOTE=bolge engeli")
if "!CODE!"=="403" (set "STATUS=HATA" & set "NOTE=erisim reddedildi - IP/bolge engeli veya bot korumasi")
if "!STATUS!"=="HATA" if "!CRIT!"=="0" set "STATUS=UYARI"
if "!STATUS!"=="HATA" set /a FAILS+=1
if "!STATUS!"=="UYARI" set /a WARNS+=1
set "LINE=[!STATUS!] !NAME!: HTTP !CODE!, !SECS! sn, !NOTE!"
echo   !LINE!
>> "%OUT%" echo !LINE!
exit /b 0

:no_curl
echo ==================================================
echo   SONUC: HATA - curl.exe bulunamadi
echo ==================================================
echo Windows 10 1803 veya daha yeni bir surum gerekir.
> "%OUT%" echo SONUC: HATA - curl.exe bulunamadi
pause
exit /b 1
