@echo off
setlocal EnableExtensions
cd /d "%~dp0"

echo.
echo === Edgecute local ===
echo.

REM ---- Seguros obligatorios (AGENTS.md): sin esto, local puede tocar produccion ----
if not exist "backend\.env" goto :noenv
findstr /B /C:"DISABLE_GCS_SYNC=true" "backend\.env" >nul
if errorlevel 1 goto :nogcs
findstr /B /C:"LIVE_SCREENER_ENABLED=false" "backend\.env" >nul
if errorlevel 1 goto :nolive
echo [OK] Seguros verificados: DISABLE_GCS_SYNC=true y LIVE_SCREENER_ENABLED=false

REM ---- Backend en :8010 ----
set BACKEND_STARTED=0
netstat -ano | findstr ":8010" | findstr "LISTENING" >nul
if not errorlevel 1 goto :backend_up
if exist "backend\.venv\Scripts\python.exe" goto :start_backend
echo [SETUP] Creando venv e instalando dependencias del backend - solo la primera vez...
python -m venv backend\.venv
if errorlevel 1 goto :nopython
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto :nopython
:start_backend
echo [START] Backend en http://localhost:8010 - ventana: edgecute-backend
start "edgecute-backend" cmd /k "cd backend && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8010"
set BACKEND_STARTED=1
:backend_up
if %BACKEND_STARTED%==1 goto :frontend
echo [OK] Backend ya escuchaba en :8010

:frontend
REM ---- Frontend en :3000 ----
netstat -ano | findstr ":3000" | findstr "LISTENING" >nul
if not errorlevel 1 goto :frontend_already
if exist "frontend\node_modules" goto :start_frontend
echo [SETUP] Instalando dependencias del frontend - solo la primera vez...
pushd frontend
call npm install
popd
:start_frontend
echo [START] Frontend en http://localhost:3000 - ventana: edgecute-frontend
start "edgecute-frontend" cmd /k "cd frontend && npm run dev"
goto :wait_backend
:frontend_already
echo [OK] Frontend ya escuchaba en :3000
:wait_backend

REM ---- Esperar al backend y abrir la app ----
echo.
echo Esperando al backend...
set /a tries=0
:waitloop
set /a tries+=1
curl -s -m 2 http://localhost:8010/health >nul 2>&1
if not errorlevel 1 goto :healthy
if %tries% lss 45 goto :waitmore
echo [AVISO] El backend tarda mas de 90s en responder. Revisa su log en la ventana edgecute-backend:
echo        debe aparecer "GCS sync disabled by environment variable - DISABLE_GCS_SYNC=true".
echo        Si NO aparece, cierra esa ventana y no sigas - ver AGENTS.md.
goto :open
:waitmore
timeout /t 2 /nobreak >nul
goto :waitloop
:healthy
echo [OK] Backend healthy.
:open
start http://localhost:3000
echo.
echo Listo: http://localhost:3000 - backend: http://localhost:8010/health
echo Para parar todo: parar_local.bat
echo.
exit /b 0

:noenv
echo [ABORT] Falta backend\.env. Pide los envs a Adrian - ver docs/GUIA_DEV_LOCAL_Y_DEVELOP_PARA_IA.md seccion 4.2
exit /b 1
:nogcs
echo [ABORT] backend\.env no tiene DISABLE_GCS_SYNC=true. Sin esa variable tu local puede
echo         SOBRESCRIBIR la base de datos de usuarios de PRODUCCION. No se arranca - AGENTS.md.
exit /b 1
:nolive
echo [ABORT] backend\.env no tiene LIVE_SCREENER_ENABLED=false. Sin eso peleas la conexion
echo         en vivo con produccion y degradas el screener real. No se arranca - AGENTS.md.
exit /b 1
:nopython
echo [ABORT] Fallo preparando el venv del backend. Revisa que python 3.12+ este en PATH.
exit /b 1
