Este es el archivo de especificaciones técnicas en formato Markdown diseñado para ser procesado por el agente de **Antigravity**. El documento detalla las reestructuraciones de lógica, nomenclatura y restricciones de los indicadores en las secciones de "PATTERN" e "INDICATOR".

---

# Plan de Implementación: Reestructuración de Indicadores y Lógica de Confrontación

Este documento contiene las instrucciones precisas para modificar la arquitectura de indicadores de la aplicación, divididas por categorías y reglas de validación.

## 1. Cambios Estructurales de Categorías
* **ELIMINACIÓN TOTAL:** Eliminar la clasificación/lista de indicadores denominada **"PATTERN"**. Esta categoría ya no debe existir en la interfaz ni en la lógica del backtester.
* **PERSISTENCIA:** En la lista **"INDICATOR"**, el parámetro `Bars back(X)` debe mantenerse intacto en su funcionamiento actual.

---

## 2. Reestructuración de la Lista "INDICATOR"

### A. Grupo de Superposición (Overlays)
*Aplicable a: SMA, EMA, WMA, VWAP, AVWAP (Anchored), Linear Regression, Zig Zag, Ichimoku Clouds.*

* **Regla de Confrontación:** **NO** pueden enfrentarse a:
    * Momentum & Oscillators.
    * Volatility.
    * Volume.
    * Behaviour & Patterns.
    * Time & Others.
* **Excepciones permitidas:** Pueden enfrentarse contra **Parabolic SAR** y **Bollinger Bands**.
* **Resto:** Pueden enfrentarse contra cualquier otra opción del desplegable.

### B. Momentum & Oscillators (Restricciones Específicas)
| Indicador | Regla de Confrontación / Cambio |
| :--- | :--- |
| **RSI** | Solo contra otro **RSI** o **Fixed Value**. |
| **MACD** | Solo contra otro **MACD** o **Fixed Value**. **Mejora:** Debe permitir seleccionar el parámetro específico: **Signal**, **MACD Line**, o **Histogram**. |
| **Stochastic** | Solo contra otro **Stochastic** o **Fixed Value**. |
| **Momentum** | Solo contra otro **Momentum** o **Fixed Value**. |
| **CCI** | Solo contra otro **CCI** o **Fixed Value**. |
| **ROC** | Solo contra otro **ROC** o **Fixed Value**. |
| **DMI** | **Dividir en dos:** `DMI+` y `DMI-`. Añadir selector de **Periodo**. Solo contra Momentum & Oscillators o **Fixed Value**. |
| **Williams %R**| Solo contra otro **Williams %R** o **Fixed Value**. |

### C. Volatility & Volume
* **ATR / ADX:** Solo contra sí mismos (mismo tipo) o **Fixed Value**.
* **Bollinger Bands:** No contra Momentum, Volatility, Volume, Behaviour o Time. **Excepciones:** Parabolic SAR, Donchian u otro Bollinger.
* **Donchian (NUEVO):** Añadir indicador. Mismas reglas de Bollinger Bands.
* **Parabolic SAR:** Mismas reglas que el Grupo A (Overlays).
* **Volume / Acumulated Volume:** Solo contra sí mismos o **Fixed Value**.
* **RVOL:** Añadir selector de **Periodo**. Solo contra otro RVOL o **Fixed Value**.
* **OBV:** Añadir selector de **Periodo**.
* **ELIMINAR:** `Medaugh Shading`, `Vol Accum/Distribution`.

### D. Behaviour & Patterns (Nomenclatura y Lógica)
| Anterior | Nuevo Nombre / Acción | Restricción de Confrontación |
| :--- | :--- | :--- |
| **Close** | **Bar Close** | No contra Momentum, Volume o Time. |
| **Open** | **Bar Open** | No contra Momentum, Volume o Time. |
| **High** | **High Bar** | No contra Momentum, Volume o Time. |
| **Low** | **Low Bar** | No contra Momentum, Volume o Time. |
| **HOD** | **RTH High** | No contra Momentum, Volume o Time. |
| **LOD** | **RTH Low** | No contra Momentum, Volume o Time. |
| **Day Open** | **RTH Open** | No contra Momentum, Volume o Time. |
| **Yesterday...** | (High/Low/Open/Close) | No contra Momentum, Volume o Time. |

**Nuevos Indicadores de Conteo (Requieren campo "Fixed Value" adjunto):**
* **Consecutive Higher Highs:** Cantidad de máximos crecientes.
* **Consecutive Higher Lows (NUEVO):** Cantidad de mínimos crecientes.
* **Consecutive Lower Lows:** Cantidad de mínimos decrecientes.
* **Consecutive Lower Highs (NUEVO):** Cantidad de máximos decrecientes.
* **Consecutive Green/Red Candles:** Cantidad de velas del mismo color.

**Lógica de Opening Range:**
* **Opening Range RTH:** Dividir en `Opening Range +` (Máximo) y `Opening Range -` (Mínimo). Añadir input de **Minutos**.
* **Opening Range AM (NUEVO):** Mismo funcionamiento que RTH pero basado en After Hours.

**Heikin-Ashi:**
* **Nomenclatura única:** `Heikin-Ashi`.
* Al seleccionar, desplegar sub-opciones: `Close Bar`, `Open Bar`, `High Bar`, `Low Bar`, `Consecutive Green`, `Consecutive Red`.
* Las opciones `Consecutive` solo contra **Fixed Value**.

### E. Time & Others (Nuevas Funciones)
* **Time of Day:** Sin comparación. Fija la hora de inicio de la condición.
* **Range of Time (NUEVO):** Definir minutos de operación desde la entrada.
* **High/Low from x time (NUEVO):** Calcula el High/Low desde una hora fija hasta la vela actual (dinámico).
* **High/Low from hour-time (ORB+/-) (NUEVO):** Requiere campos "From" (hora) y "Range" (minutos).
* **ELIMINAR:** `Current Open`, `Bar Open`, `Previous Close`, `Pivot Points`, `Max N Bars`, `Custom`.

---

## 3. Reestructuración de la Lista "DISTANCE"

### A. Limpieza de Sub-apartado
* **ELIMINAR:** `Chaikin Money Flow`, `Medaugh Shading`, `Max N Bars`, `Custom`, `Time of Day`, `Pivot Points`, `MACD` y todos los de **Time & Others**.
* **ELIMINAR de Behaviour & Patterns:** Todos excepto **Opening Range** (con la nueva lógica de + / -).

### B. Reglas de Confrontación en Distancia
* **SMA, EMA, WMA, VWAP, AVWAP, Linear Reg, Zig Zag, Ichimoku:** No contra Momentum, Volatility, Volume, Behaviour o Time. **Excepciones:** Parabolic SAR y Bollinger.
* **Bollinger Bands / Donchian:** Al usarlos en Distancia, **DEBE** permitir seleccionar qué línea se mide: **Upper** o **Lower**.
* **Parabolic SAR, Bar Close, Bar Open, High Bar, Low Bar, RTH High, RTH Low, PM High, PM Low:** No contra Momentum, Volume o Time.
* **Yesterday (H/L/O/C) y Max/Min last X days:** No contra Momentum, Volume, Time ni contra indicadores dentro de **Behaviour & Patterns**.

---

## 4. Otros Ajustes Finales
* **Ret % PM:** Añadir campo para el parámetro `%`. Solo contra sí mismo o Fixed Value.
* **Ret % RTH:** Añadir campo para el parámetro `%`. Solo contra Ret % PM, sí mismo o Fixed Value.
* **ELIMINAR:** `Ret % AM`.

---
**¿Deseas que genere el esquema de base de datos o el JSON de configuración para estos nuevos validadores de confrontación?**