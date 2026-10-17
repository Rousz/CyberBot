@echo off
rem UTCNOW ve ISTNOW degiskenlerini ayarlar (cagiran .bat kullanir). Tum zamanlar UTC tutulur.
set "UTCNOW=bilinmiyor"
set "ISTNOW=bilinmiyor"
for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command "[DateTime]::UtcNow.ToString('yyyy-MM-dd HH:mm:ss')"`) do set "UTCNOW=%%t"
for /f "usebackq delims=" %%t in (`powershell -NoProfile -Command "[TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Turkey Standard Time').ToString('yyyy-MM-dd HH:mm:ss')"`) do set "ISTNOW=%%t"
exit /b 0
