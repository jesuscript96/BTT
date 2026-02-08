# Análisis de Métricas: Especificación vs Implementación

## Resumen Ejecutivo

Este documento compara las métricas definidas en la especificación del usuario contra lo que está:
1. **Implementado** en la tabla `daily_metrics`
2. **Testeado** en el suite de tests actual

---

## Métricas por Categoría

### 📊 PRECIOS

| Métrica | Columna DB | Implementada | Testeada | Estado |
|---------|------------|--------------|----------|---------|
| Open Price | `rth_open` | ✅ | ✅ | OK |
| Close Price | `rth_close` | ✅ | ✅ | OK |
| High Price (HOD) | `rth_high` | ✅ | ✅ | OK |
| Low Price (LOD) | `rth_low` | ✅ | ✅ | OK |
| Previous Day Close | ❌ | ❌ | ❌ | **FALTA** |
| Pre-Market High (PMH) | `pm_high` | ✅ | ✅ | OK |
| M1, M5, M15... M180 Price | ❌ | ❌ | ❌ | **FALTA** |

---

### 📈 VOLUMEN

| Métrica | Columna DB | Implementada | Testeada | Estado |
|---------|------------|--------------|----------|---------|
| EOD Volume (RTH) | `rth_volume` | ✅ | ✅ | OK |
| Premarket Volume | `pm_volume` | ✅ | ✅ | OK |

---

### 🚀 GAP & RUN

| Métrica | Columna DB | Implementada | Testeada | Estado |
|---------|------------|--------------|----------|---------|
| Open Gap % | `gap_at_open_pct` | ✅ | ✅ | OK |
| PMH Gap % | ❌ | ❌ | ❌ | **FALTA** |
| RTH Run % | `rth_run_pct` | ✅ | ✅ | OK |
| PMH Fade to Open % | `pmh_fade_to_open_pct` | ✅ | ✅ | OK |
| RTH Fade to Close % | `rth_fade_to_close_pct` | ✅ | ✅ | OK |

---

### ⚡ VOLATILITY

| Métrica | Columna DB | Implementada | Testeada | Estado |
|---------|------------|--------------|----------|---------|
| RTH Range % | ❌ | ❌ | ❌ | **FALTA** |
| High Spike % | `high_spike_pct` | ✅ | ✅ | OK |
| Low Spike % | `low_spike_pct` | ✅ | ✅ | OK |
| M(x) High Spike % | ❌ | ❌ | ❌ | **FALTA** |
| M(x) Low Spike % | ❌ | ❌ | ❌ | **FALTA** |

---

### 📉 INTRADAY RETURN

| Métrica | Columna DB | Implementada | Testeada | Estado |
|---------|------------|--------------|----------|---------|
| Day Return % | ❌ | ❌ | ❌ | **FALTA** |
| M15 Return % | `m15_return_pct` | ✅ | ✅ | OK |
| M30 Return % | `m30_return_pct` | ✅ | ✅ | OK |
| M60 Return % | `m60_return_pct` | ✅ | ✅ | OK |
| Return % From M(x) to Close | ❌ | ❌ | ❌ | **FALTA** |

---

### 📅 HISTORICAL RETURN

| Métrica | Columna DB | Implementada | Testeada | Estado |
|---------|------------|--------------|----------|---------|
| 1 Month Return | ❌ | ❌ | ❌ | **FALTA** |
| 3 Months Return | ❌ | ❌ | ❌ | **FALTA** |
| 1 Year Return | ❌ | ❌ | ❌ | **FALTA** |
| 2 Year Return | ❌ | ❌ | ❌ | **FALTA** |
| 3 Year Return | ❌ | ❌ | ❌ | **FALTA** |

---

### 📊 INTRADAY VWAP

| Métrica | Columna DB | Implementada | Testeada | Estado |
|---------|------------|--------------|----------|---------|
| VWAP at Open | ❌ | ❌ | ❌ | **FALTA** |
| VWAP at M5, M(x) | ❌ | ❌ | ❌ | **FALTA** |
| open_lt_vwap (boolean) | `open_lt_vwap` | ✅ | ✅ | OK |

---

### ⏰ TIME

| Métrica | Columna DB | Implementada | Testeada | Estado |
|---------|------------|--------------|----------|---------|
| HOD Time | `hod_time` | ✅ | ✅ | OK |
| LOD Time | `lod_time` | ✅ | ✅ | OK |
| PM High Time | ❌ | ❌ | ❌ | **FALTA** |

---

### ✅ OTROS (Implementados pero no en spec)

| Métrica | Columna DB | Implementada | Testeada | Notas |
|---------|------------|--------------|----------|-------|
| PM High Break | `pm_high_break` | ✅ | ✅ | Boolean |
| Close < M15 | `close_lt_m15` | ✅ | ✅ | Boolean |
| Close < M30 | `close_lt_m30` | ✅ | ✅ | Boolean |
| Close < M60 | `close_lt_m60` | ✅ | ✅ | Boolean |
| Close Direction | `close_direction` | ✅ | ✅ | VARCHAR |

---

## 🎯 Resumen de Brechas

### Columnas que FALTAN en `daily_metrics`:
1. `prev_close` (Previous Day Close)
2. `pmh_gap_pct` (PMH Gap %)
3. `rth_range_pct` (RTH Range %)
4. `day_return_pct` (Day Return %)
5. `pm_high_time` (PM High Time)
6. Métricas M(x) High/Low Spike
7. Métricas Return From M(x) to Close
8. Métricas Historical Return (1M, 3M, 1Y, 2Y)
9. Métricas VWAP at M(x)

### Tests que FALTAN (para métricas YA implementadas):
**Todos los tests necesarios para las métricas implementadas YA EXISTEN ✅**

---

## 📋 Plan de Acción

### Opción 1: Solo Testear lo Implementado (ACTUAL)
✅ **YA COMPLETADO**: 93/94 tests pasando para todas las métricas implementadas

### Opción 2: Implementar Métricas Faltantes
1. Agregar columnas faltantes a `daily_metrics`
2. Actualizar lógica de cálculo en processor/ingestion
3. Crear tests para nuevas métricas
4. Ejecutar migración de datos históricos

---

## ❓ Pregunta para el Usuario

**¿Qué prefieres hacer?**

**A)** Mantener el sistema actual (solo testear lo que YA está implementado) ✅ LISTO

**B)** Implementar las métricas faltantes del documento + sus tests

**C)** Implementar solo métricas específicas (dime cuáles)
