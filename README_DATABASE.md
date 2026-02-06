# Guía de Configuración: DuckDB (Almacenamiento Local)

¡Hola! DuckDB **no es un servicio en la nube** como AWS o Google Cloud. Es un motor de base de datos **local** que vive dentro de tu carpeta de proyecto. No necesitas crear ninguna cuenta, ni pagar suscripciones, ni configurar servidores.

Aquí tienes los pasos para que tú puedas gestionar y ver los datos:

## 1. ¿Dónde están mis datos?
Toda la información histórica que descargamos de Massive se guarda en este archivo:
`backend/backtester.duckdb`

Es un único archivo que contiene todo el histórico comprimido y optimizado.

## 2. Cómo ver los datos manualmente (Recomendado)
Si quieres abrir la base de datos como si fuera un Excel para "tocar" los datos, te recomiendo instalar una herramienta gratuita:

### Opción A: DBeaver (La más completa)
1. Descarga e instala [DBeaver Community](https://dbeaver.io/download/).
2. Abre DBeaver y dale a "Nueva Conexión".
3. Busca **DuckDB** en la lista.
4. En "Path", selecciona el archivo `backend/backtester.duckdb` de este proyecto.
5. ¡Listo! Podrás ver las tablas `tickers` y `historical_data`.

### Opción B: Extensión de VS Code
1. Busca la extensión `SQLTools` y el driver `SQLTools DuckDB Driver`.
2. Podrás hacer consultas SQL directamente desde tu editor.

## 3. Estrategia para Miles de Tickers y Años de Datos
Para manejar el volumen masivo que mencionas sin que tu ordenador explote:

1. **Parquet Partitioning**: En lugar de meter todo en un solo archivo `.duckdb`, guardaremos los datos antiguos en archivos `.parquet` dentro de una carpeta `data/archive/`. 
   - Ejemplo: `data/archive/AAPL/2023.parquet`
2. **DuckDB Virtual Tables**: DuckDB puede leer miles de archivos Parquet instantáneamente como si fueran una sola tabla gigante.
3. **Ingestión por Lotes**: Dado que Massive API tiene límites (Rate Limits), el script de `bulk_load.py` debe ejecutarse con pausas o por grupos de tickers para no ser bloqueado.

## 4. Pasos manuales que debes hacer tú
1. **Instalar DBeaver**: Para que pierdas el miedo a no "ver" dónde está la info.
2. **Proporcionar espacio en disco**: Asegúrate de tener espacio suficiente si planeas bajar terabytes de datos (aunque Parquet comprime muchísimo).
3. **Ejecutar Ingestión**: Cuando quieras bajar más datos, simplemente corre `python bulk_load.py` en la carpeta `backend`.
