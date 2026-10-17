@echo off
rem CyberBot - .env dosyasini olusturur (yoksa) ve Not Defteri ile acar.
rem .env gizli bilgileri tutar ve SADECE bu bilgisayarda durur, GitHub'a gitmez.
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title CyberBot - .env dosyasi
if not exist "reports" mkdir "reports"
call "setup\stamp.bat"

set "ACTION=acildi"
if exist ".env" goto :open
copy ".env.example" ".env" >nul
if errorlevel 1 goto :failed
set "ACTION=olusturuldu"

:open
echo .env %ACTION%. Not Defteri aciliyor.
echo Degerleri esittir isaretinden sonra bosluksuz yaz, Ctrl+S ile kaydet ve Not Defteri'ni kapat.
echo UYARI: .env icindeki bilgileri kimseyle paylasma, sohbete de yapistirma.
start "" /wait notepad.exe ".env"
>> "reports\setup_history.txt" echo %UTCNOW% UTC - setup_env: BASARILI - .env %ACTION%
echo.
echo ==================================================
echo   SONUC: BASARILI - .env %ACTION%
echo ==================================================
echo Kapatmak icin bir tusa bas.
pause >nul
exit /b 0

:failed
>> "reports\setup_history.txt" echo %UTCNOW% UTC - setup_env: HATA - .env olusturulamadi
echo ==================================================
echo   SONUC: HATA - .env olusturulamadi
echo ==================================================
echo .env.example dosyasi bu klasorde mi? GitHub Desktop ile son hali cektin mi?
pause
exit /b 1
