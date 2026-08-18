@echo off
setlocal EnableExtensions
echo Parando edgecute local...

REM Mata las ventanas arrancadas por arrancar_local.bat (con todo su arbol de procesos)
taskkill /FI "WINDOWTITLE eq edgecute-backend*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq edgecute-frontend*" /T /F >nul 2>&1

REM Red de seguridad: si algo sigue escuchando en los puertos, lo mata por PID
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8010" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":3000" ^| findstr "LISTENING"') do taskkill /PID %%p /F >nul 2>&1

echo Hecho. Backend :8010 y frontend :3000 detenidos.
pause
