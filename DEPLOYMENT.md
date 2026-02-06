# Guía de Deployment - BTT

## 📋 Pasos para GitHub y Vercel

### 1️⃣ Preparación del Repositorio GitHub

#### Pasos Manuales:
1. Ve a https://github.com/new
2. Crea un nuevo repositorio:
   - **Nombre**: `BTT` (o el que prefieras)
   - **Visibilidad**: Private (recomendado) o Public
   - **NO** inicialices con README, .gitignore o licencia (ya los tenemos)
3. Copia la URL del repositorio (ejemplo: `https://github.com/tu-usuario/BTT.git`)

#### Comandos Automáticos (ya ejecutados):
```bash
cd /Users/jvch/Desktop/AutomatoWebs/BTT
git init
git add .
git commit -m "Initial commit: Trading backtester with real metrics"
```

#### Comando Manual (ejecutar después de crear el repo):
```bash
git remote add origin https://github.com/TU-USUARIO/BTT.git
git branch -M main
git push -u origin main
```

---

### 2️⃣ Deployment del Backend

**Opciones recomendadas:**

#### Opción A: Railway (Recomendada - Soporta DuckDB)
1. Ve a https://railway.app
2. Conecta tu cuenta de GitHub
3. Click en "New Project" → "Deploy from GitHub repo"
4. Selecciona el repositorio `BTT`
5. Configura:
   - **Root Directory**: `backend`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. Añade variables de entorno:
   - `MASSIVE_API_KEY`: tu API key de Polygon.io
   - `MASSIVE_API_BASE_URL`: `https://api.polygon.io`
7. Deploy
8. Copia la URL del backend (ejemplo: `https://btt-production.up.railway.app`)

#### Opción B: Render
1. Ve a https://render.com
2. New → Web Service
3. Conecta GitHub y selecciona el repo
4. Configura:
   - **Root Directory**: `backend`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
5. Añade las mismas variables de entorno
6. Deploy

---

### 3️⃣ Deployment del Frontend en Vercel

#### Pasos Manuales:
1. Ve a https://vercel.com
2. Click en "Add New" → "Project"
3. Importa tu repositorio de GitHub `BTT`
4. Configura el proyecto:
   - **Framework Preset**: Next.js (auto-detectado)
   - **Root Directory**: `frontend`
   - **Build Command**: `npm run build` (auto)
   - **Output Directory**: `.next` (auto)
5. Añade variable de entorno:
   - **Key**: `NEXT_PUBLIC_API_URL`
   - **Value**: URL de tu backend (de Railway o Render)
   - Ejemplo: `https://btt-production.up.railway.app/api`
6. Click en "Deploy"
7. Espera 2-3 minutos
8. ¡Listo! Tu app estará en `https://tu-proyecto.vercel.app`

---

### 4️⃣ Verificación Post-Deployment

1. Abre tu app en Vercel
2. Verifica que el dashboard cargue
3. Prueba los filtros
4. Revisa que los datos se actualicen

---

### 🔧 Troubleshooting

**Si el frontend no conecta con el backend:**
- Verifica que `NEXT_PUBLIC_API_URL` esté correctamente configurada en Vercel
- Asegúrate de que el backend esté corriendo (revisa logs en Railway/Render)
- Verifica que el backend tenga CORS configurado para el dominio de Vercel

**Si el backend falla:**
- Revisa que `MASSIVE_API_KEY` esté configurada
- Verifica los logs del servicio
- Asegúrate de que DuckDB pueda crear archivos (Railway soporta esto)

---

### 📝 Notas Importantes

- **Base de Datos**: DuckDB se reiniciará en cada deploy. Para persistencia, considera migrar a PostgreSQL en producción.
- **API Limits**: El tier gratuito de Polygon.io tiene límites. Ajusta el scheduler si es necesario.
- **Costos**: Railway y Vercel tienen tiers gratuitos, pero monitorea el uso.

---

### 🔄 Actualizaciones Futuras

Para actualizar el código:
```bash
git add .
git commit -m "Descripción de cambios"
git push
```

Vercel y Railway auto-deployarán los cambios.
