@echo off
rem ===========================================================================
rem Watchdog del backend BTT (pedido por Alvaro 2026-08-28: "para siempre").
rem
rem - Si el puerto 8010 esta LIBRE: arranca uvicorn (config habitual:
rem   --reload) y lo revive si muere, con 30 s de espera entre intentos.
rem - Si el puerto esta OCUPADO (instancia manual de Alvaro u otra): NO duplica,
rem   espera 60 s y vuelve a mirar. Cuando esa instancia se cierra, este
rem   watchdog retoma el puerto.
rem - Log: ..\..\backend_prof.log (rotado a _old.log si pasa de 50 MB).
rem   Vidas del watchdog: ..\..\backend_watchdog.log
rem
rem Registrado como tarea programada "BTT backend watchdog" (inicio de sesion,
rem sin limite de tiempo). Quitar con:
rem   schtasks /Delete /TN "BTT backend watchdog" /F
rem ===========================================================================
setlocal
cd /d "%~dp0.."

:loop
netstat -ano | findstr "LISTENING" | findstr ":8010 " >nul 2>&1
if %errorlevel%==0 (
    rem Puerto ocupado por otra instancia: no duplicar, esperar.
    timeout /t 60 /nobreak >nul
    goto loop
)

rem Rotar log si crece demasiado (50 MB): se pierde solo el log anterior.
for %%F in ("..\backend_prof.log") do if %%~zF GTR 52428800 move /y "..\backend_prof.log" "..\backend_prof_old.log" >nul 2>&1

echo [%date% %time%] watchdog: puerto libre, arrancando backend >> ..\backend_watchdog.log
".venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8010 >> ..\backend_prof.log 2>&1
echo [%date% %time%] watchdog: backend murio (code %errorlevel%), reintento en 30 s >> ..\backend_watchdog.log
timeout /t 30 /nobreak >nul
goto loop
