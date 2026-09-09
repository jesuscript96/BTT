@echo off
rem ===========================================================================
rem Arranque seguro del backend local BTT (envoltorio humano/agente).
rem
rem Siempre usa backend\.venv\Scripts\python.exe (nunca un python del PATH ni
rem del sistema) y JAMAS --reload: local_data.duckdb admite un solo dueno.
rem Toda la logica de guardas esta en scripts\run_backend_safe.py:
rem   - aborta si el puerto 8010 ya esta ocupado (dice quien lo tiene)
rem   - aborta si otro proceso retiene local_data.duckdb (traduce el error)
rem   - exige DISABLE_GCS_SYNC=true y LIVE_SCREENER_ENABLED=false
rem
rem Reglas completas: docs\REGLA_ARRANQUE_BACKEND_LOCAL.md
rem ===========================================================================
setlocal
set "VENV_PY=%~dp0..\.venv\Scripts\python.exe"

if not exist "%VENV_PY%" (
    echo [ABORT] No existe %VENV_PY%
    echo         Crea el venv primero: cd backend ^&^& python -m venv .venv
    exit /b 1
)

"%VENV_PY%" "%~dp0run_backend_safe.py" %*
exit /b %errorlevel%
