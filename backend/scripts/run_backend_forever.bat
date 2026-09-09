@echo off
rem ===========================================================================
rem Watchdog del backend BTT (pedido por Alvaro 2026-08-28: "para siempre").
rem
rem REGLA DE ORO (docs/REGLA_ARRANQUE_BACKEND_LOCAL.md): UN solo proceso puede
rem tener abierto local_data.duckdb. Este watchdog:
rem   - NUNCA usa --reload (los workers spawn_main huerfanos retenian la base:
rem     bloqueos de la carga de las 09:00 el 2026-09-05 y 2026-09-07).
rem   - Solo arranca via scripts\run_backend_safe.py (venv propio, 1 worker),
rem     que a su vez se niega a arrancar si el puerto 8010 o el DuckDB estan
rem     ocupados por otro proceso.
rem   - Si la carga de las 09:00 (tarea "Edgecute Actualizar Datos Diario" de
rem     cangrejo_data) retiene el DuckDB con el puerto libre, el launcher se
rem     autodetiene (exit 3) y este loop reintenta a los 30 s sin pisar nada.
rem   - Puerto 8010 ocupado (instancia manual o la de la tarea de cangrejo):
rem     NO duplica, espera 60 s y vuelve a mirar.
rem
rem - Log del backend: ..\..\backend_prof.log (rotado a _old.log > 50 MB).
rem   Vidas del watchdog: ..\..\backend_watchdog.log
rem
rem Registrado como tarea programada "BTT backend watchdog" (inicio de sesion,
rem sin limite de tiempo). Quitar con:
rem   schtasks /Delete /TN "BTT backend watchdog" /F
rem Reactivar (desde una consola admin):
rem   schtasks /Create /TN "BTT backend watchdog" /SC ONLOGON /RL LIMITED ^
rem     /TR "\"%~f0\"" /F
rem
rem NOTA: `timeout` NO espera cuando no hay consola (Task Scheduler): devuelve
rem al instante y provoco un crash-loop el 2026-09-05. Los sleeps usan ping.
rem ===========================================================================
setlocal
cd /d "%~dp0.."

:loop
netstat -ano | findstr "LISTENING" | findstr ":8010 " >nul 2>&1
if %errorlevel%==0 (
    rem Puerto ocupado por otra instancia: no duplicar, esperar.
    ping -n 61 127.0.0.1 >nul
    goto loop
)

rem Rotar log si crece demasiado (50 MB): se pierde solo el log anterior.
for %%F in ("..\backend_prof.log") do if %%~zF GTR 52428800 move /y "..\backend_prof.log" "..\backend_prof_old.log" >nul 2>&1

echo [%date% %time%] watchdog: puerto libre, arrancando backend >> ..\backend_watchdog.log
call "%~dp0arrancar_backend.bat" >> ..\backend_prof.log 2>&1
echo [%date% %time%] watchdog: backend murio (code %errorlevel%), reintento en 30 s >> ..\backend_watchdog.log
ping -n 31 127.0.0.1 >nul
goto loop
