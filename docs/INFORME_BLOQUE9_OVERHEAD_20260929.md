# Informe — Bloque 9 · Zonas de overhead (2026-09-29)

> Pedido de Álvaro (hoja de ruta). Pregunta: si ARRIBA del precio de entrada
> hay "techo" (máximos de 20/60/250 sesiones, el máximo del último runner) o
> volumen previo atrapado, ¿cambia el trade? **TODO medido con el precio en el
> MINUTO DE ENTRADA** (hallazgo 18: nada del día D que se complete después de
> la entrada). Reglas fijas: sin look-ahead, un trade = una fila, verificación
> a mano de lo que salga ✅, la última palabra es el backtest de Álvaro en la app.

## Datos y método

- **Universo:** vistaA limpia (PMH ≥ 50 %, 2019-2026): 13.983 ticker-días. P de
  referencia = cierre de la PRIMERA vela del premarket (causal). Outcome:
  `pmh_fade_pct`. Controles: 1.6 (neto RTH víspera), 3.2 (ret 5 d), 6.1 (IPO).
- **Trades:** 1B (B0, 4.482 trades 2024-26). P = precio medio de entrada REAL
  (con pirámide). El "máximo corrido" del día = max de highs 04:00→minuto de
  entrada (velas 1m). Outcome: `return_pct`.
- **Features:**
  - `ovh_N` = (max high de las N sesiones PREVIAS − P)/P ×100. N = 20/30/60/90/250.
    Negativo = el precio YA está por encima de ese máximo (lo rompió).
  - `runner` = lo mismo en 30/60/90 (el "runner" reciente) + categoría del
    corrido hasta la entrada contra max_60: `rompe` (>100 %) / `llega`
    (≥95 %) / `corto` (<95 %).
  - `vol_encima_5` = $ negociados POR ENCIMA de P en las 5 sesiones previas,
    con velas 1m (fracción (high−P)/(high−low) por vela, 0-1). Cobertura 99,2 %.
- **Verificación a mano:** 12/12 trades (ovh_60 recomputado del daily crudo +
  corrido hasta entrada de las velas crudas, idénticos) y vol_encima en casos
  con volumen (2/4 inicial → la diferencia era que el pipeline usaba la E del
  primer trade del día en reentradas; re-agregado por E propia de CADA trade y
  verificado). Sin ✅ a nivel de estrategia no hay nada más que verificar.

## Resultados — universo (fade del día)

| feature | ρ buscar (19-22) | ρ confirmar (23-26) | años mismo signo | parcial ctrl | lectura |
|---|---|---|---|---|---|
| ovh_20 | +0,049 | +0,024 | 6/8 | +0,074 | débil |
| ovh_30 | +0,064 | +0,024 | 6/8 | +0,076 | débil |
| **ovh_60** | **+0,087** | **+0,026** | **7/8** | **+0,081** | débil pero estable |
| ovh_90 | +0,084 | +0,023 | 7/8 | +0,073 | débil |
| ovh_250 | +0,149 | +0,016 | 5/8 | +0,052 | se apaga al confirmar |

Deciles de ovh_20: fade 25,4-26,0 % (precio rompiendo o pegado al máximo) →
28,6-28,8 % (techo muy lejos): **+3 pp entre extremos, monótono pero suave.**
Categorías vs runner60: «>20 % debajo del runner» fade 28,1 % vs «rompe/llega»
25,5-25,9 % — misma dirección, ~2,5 pp.

## Resultados — trades 1B (al minuto de entrada)

| feature | ρ 2024 / 2025 / 2026 | parcial ctrl | deciles |
|---|---|---|---|
| ovh_20 | +0,048 / +0,026 / +0,021 | +0,031 | zigzag, no monótonos |
| ovh_60 | +0,027 / +0,040 / +0,018 | +0,029 | zigzag |
| ovh_250 | −0,062 / +0,041 / +0,071 | +0,022 | signo cruzado |
| ratio_runner60 | −0,000 / −0,014 / +0,014 | −0,002 | nada |
| **vol_encima_5** | +0,052 / +0,006 / −0,016 | ≈0 | 0 $: 2,76 % · 0-1 M$: 4,31 % · 1-5 M$: 3,09 % · 5-20 M$: 2,55 % · >20 M$: 3,97 % — sin patrón |

Categorías del runner (corrido hasta la entrada vs max_60): `corto` +3,62 %
(n=2.665) · `llega` +2,07 % (n=196) · `rompe` +2,51 % (n=1.621). La dirección
"corto mejor que rompe" aparece en 2024 y 2026 pero no limpia en 2025 —
**no consistente**.

## Conclusión

**Bloque 9 cerrado SIN construcción.** El overhead es un descriptor de
universo DÉBIL (más techo encima → algo más de fade, 7/8 años, +3 pp entre
extremos) que la 1B no convierte en edge: ρ ≈ +0,02-0,05 con deciles en
zigzag, el runner rompe/llega/corto no es consistente por año y el volumen
previo por encima del precio es ruido puro. Mismo patrón que Bloque 8:
el día "con espacio" fadea algo más, pero la 1B entra y sale antes de que
ese espacio importe. Registrado todo, incluidos los descartes.
