# 04 — UI y Componentes

Este documento especifica el diseño visual, los estados y las interacciones frontend del módulo de Dilución y Runner.

---

## 1. Reducción de Tamaño de los Cuadros de Métricas (Cards)

El usuario solicita hacer los cuadros de métricas iniciales (Probabilidad de Dilución, Supervivencia de Caja y Estructura del Float) más pequeños.

### 1.1 Especificaciones de Estilos
*   **Contenedor Grid:** Ajustar `minmax(220px, 1fr)` a `minmax(160px, 1fr)` para comprimir las tarjetas horizontalmente.
*   **Paddings:** Reducir el padding de las tarjetas de `16px` a `10px`.
*   **Tipografía de Título:** Reducir tamaño de letra de labels de `9px` a `8px` y mantener General Sans Bold UPPERCASE.
*   **Tipografía de Cifra:** Reducir de `24px` a `18px` (General Sans Mono) y mantener el font Fraunces Serif para métricas de score y runway.
*   **Espaciado Interno:** Cambiar el gap interno de `10px` a `6px` para reducir altura total.
*   **Barras de Progreso:** Reducir la altura del riel de la barra de progreso de `6px` a `4px`.

---

## 2. Pestañas "Filings" y "Balance"

Se reemplaza el bloque estático de "Latest SEC Filings" por un contenedor de pestañas.

### 2.1 Maqueta de Pestañas (Wireframe Textual)
```
+-------------------------------------------------------------+
| LATEST SEC FILINGS       [ Filings ]  [ Balance ]           |
+-------------------------------------------------------------+
| (Si Pestaña "Filings" seleccionada)                         |
| [Financials 10-K/Q]   [News 8-K]       [Offerings 424B/S-1] |
| [Ownership 13G/D]     [Proxies 14A]    [Others]             |
|                                                             |
| (Si Pestaña "Balance" seleccionada)                         |
| Fecha      | Cash   | Debt  | Working Cap | Equity | Shares |
| -----------|--------|-------|-------------|--------|--------|
| 2026-03-31 | $8.2M  | $2.0M | $6.2M       | $13.2M | 55.0M  |
| 2025-12-31 | $12.5M | $1.5M | $11.0M      | $15.0M | 42.0M  |
+-------------------------------------------------------------+
```

### 2.2 Estilo de la Tabla Balance
*   **Encabezados:** Fondo `var(--color-ec-bg-base)`, alineación izquierda para fecha, alineación derecha para datos numéricos.
*   **Bordes:** `0.5px solid var(--color-ec-border)` horizontal, sin bordes verticales (estilo limpio).
*   **Fuente:** `General Sans` 12px regular; cifras numéricas alineadas en `ui-monospace`.
*   **Resaltado:** Resaltar en rojo (`var(--color-ec-loss)`) si el incremento de Shares trimestral es > 15% (dilución severa visible).

---

## 3. Tabla de Ownership en el Reporte de Edgie

Edgie inyectará en `<edgie_metrics>` un array `ownership_list`. La UI renderizará este array en una tabla dedicada dentro del cuerpo del reporte.

### 3.1 Estructura y Ordenación de la Tabla
1.  **Cabecera de Tabla:** Accionista | Tipo | % | Acción / Detalle | Fuente | Fecha
2.  **Orden de Filas:**
    *   Filas con `type === "PERSON"` ordenadas descendentemente por `%`.
    *   Filas con `type === "INSTITUTION"` ordenadas descendentemente por `%`.
3.  **Chips de Categoría:**
    *   `PERSON`: Fondo `rgba(216, 122, 61, 0.1)`, texto `var(--color-ec-copper)`.
    *   `INSTITUTION`: Fondo `rgba(255, 255, 255, 0.05)`, texto `var(--color-ec-text-primary)`.

---

## 4. Control de Mensaje de Carga en Edgie Chat

Para evitar la repetición del mensaje *"Edgie ha cargado exitosamente..."* 6+ veces en el chat:

### 4.1 Lógica de Control de Estado
*   En `ChatBot.tsx` y `ChatBotAgentic.tsx`, el useEffect del listener `ticker-loaded` no debe añadir ciegamente un mensaje al array.
*   Se introduce una referencia de tracking `lastNotifiedTickerRef` en React.
*   Solo se añade el mensaje system al chat si:
    1.  El ticker en el evento es diferente a `lastNotifiedTickerRef.current`.
    2.  Todos los campos clave del payload (`data`, `filings`, `finvizNews`) no son nulos ni indefinidos (es decir, el ticker se ha cargado al 100% y no progresivamente).
    3.  `lastNotifiedTickerRef.current` se actualiza con el ticker actual al disparar el mensaje.
*   Durante la carga progresiva, se mostrará un único loader visual discreto en la parte superior del chat.

---

## 5. Visualización del Comando Global en la UI del Chat

Cuando Edgie llama a la herramienta global `ticker_get_analysis` de forma autónoma:
*   **Estado de Ejecución:** El chatbot mostrará un indicador de estado en la burbuja de la conversación: *"Edgie está recuperando datos financieros de [TICKER]..."*.
*   **Actualización Silenciosa:** La llamada y análisis se ejecutan de manera silenciosa para no interrumpir la navegación actual del usuario (ej. si está configurando un backtest, no se le forzará a cambiar de página, pero Edgie sí tendrá las respuestas en el chat).

