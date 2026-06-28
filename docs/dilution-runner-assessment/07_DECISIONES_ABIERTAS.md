# 07 — Decisiones Abiertas

Este documento resume las decisiones de producto y técnicas que quedan abiertas para revisión o que se asumen como defaults reversibles para simplificar el desarrollo (KISS).

---

## A. Decisiones de Producto (Dueño: Jesús / Jaume)

### A.1 Monetización y Gating (Diferido a Jesús)
*   **Decisión:** ¿Estará el reporte de dilución avanzado restringido a usuarios de pago o planes avanzados?
*   **Estado:** **Diferido**. Este PRD entrega el mecanismo técnico completo. El gating de acceso y los tiers comerciales se implementarán a través del middleware de Clerk de acuerdo a las directrices de Jesús, sin afectar el core del análisis.

---

## B. Defaults Técnicos Reversibles (Asumidos por la IA)

Para evitar bloquear el desarrollo, la IA asume los siguientes comportamientos simplificados (KISS) que pueden ser modificados posteriormente sin rehacer la arquitectura básica:

### B.1 Normalización de Nombres de Bancos
*   **Asunción:** Los nombres de los bancos extraídos por el LLM se guardarán en la base de datos en mayúsculas y eliminando puntuaciones/sufijos redundantes (ej: *"H.C. WAINWRIGHT & CO. LLC"* se guardará como *"H.C. WAINWRIGHT"*). Esto previene duplicados en los conteos de la base de datos sin necesidad de implementar algoritmos complejos de coincidencia difusa.

### B.2 Tratamiento de Datos Trimestrales Faltantes
*   **Asunción:** Si yfinance no retorna datos trimestrales para alguna celda en la pestaña "Balance" (ej: Working Capital para un trimestre específico), se mostrará una raya `"—"` en lugar de fallar la carga de la tabla completa.

### B.3 Formateo de Cifras de Acciones (Shares)
*   **Asunción:** Las acciones en circulación y flotantes en la tabla y reporte se formatearán utilizando la abreviación compacta de millones con un decimal (ej: `55.2M` para 55,200,000 acciones), facilitando la escaneabilidad visual en pantallas pequeñas.
