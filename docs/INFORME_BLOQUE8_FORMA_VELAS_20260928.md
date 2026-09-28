# Informe — Bloque 8 · Forma de las últimas velas (2026-09-28)

> Pedido de Álvaro (hoja de ruta): compresión de volatilidad (rango víspera ÷
> rango D-2/D-3, días seguidos estrechándose, rango 3 días ÷ ATR 14-20) y
> mechas (superior ÷ rango, inferior ÷ rango, mecha ÷ cuerpo; víspera y
> suma/media de 2-3 días). **Solo datos HASTA la víspera** — nada del día del
> trade por construcción. Con las REGLAS FIJAS nuevas (tras 4.4, 7.2b y los
> peores trades): sin datos post-entrada, dedup y chequeo de colisiones, verificación
> manual de todo ✅, y cartera solo orientativa.

## Datos y método

- **Universo**: vistaA limpia del Bloque 1 (PMH Gap ≥ 50 %, 2019-2026):
  13.983 ticker-días, 3.488 tickers, 0 duplicados. Outcome: `pmh_fade_pct`
  del día del gap (el estándar del programa).
- **Features** (diario de daily_metrics, OHLC; sobre filas anteriores a D,
  shifts posicionales = días de bolsa): `comp1` = rango%(D-1)/media(D-2,D-3) ·
  `racha` = días seguidos estrechándose (0-5) · `comp3_atr14/20` =
  media(rango% D-1..D-3) ÷ ATR%(14/20 días anteriores) · `ws/wi` = mecha
  sup/inf ÷ rango (víspera `*1`, media 2-3 días `*2/*3`) · `wsc` = mecha_sup
  ÷ cuerpo (víspera y media 3 días; cuerpo 0 → sin dato). Cobertura 97-100 %.
  Velas de rango 0 → NaN (excluidas).
- **Controles**: 1.6 (neto RTH víspera), 3.2 (retorno 5 días hasta D-1),
  6.1 (ipo_dias). Parcial = Spearman de residuos por rangos.
- **Verificación de cálculo**: 6/6 ejemplos recalculados a mano del OHLC crudo
  del lago (query independiente) — comp1 y ws1 IDÉNTICOS al parquet.

## Resultados — universo (buscar 2019-22 / confirmar 2023-26)

| feature | ρ buscar | ρ confirmar | años mismo signo | parcial ctrl 1.6+3.2+6.1 |
|---|---|---|---|---|
| comp1 (compresión simple) | +0,00 | −0,03 | 2/8 | +0,03 |
| comp3_atr14 / atr20 | −0,03 | −0,01 | 7/8 | +0,02 |
| racha estrechándose | −0,01 | +0,01 | 4/8 | −0,01 |
| **ws1 (mecha sup víspera)** | **+0,02** | **+0,06** | **7/8** (solo 2021 en contra) | **+0,067** |
| wsc1 (mecha sup ÷ cuerpo) | +0,03 | +0,06 | 7/8 | +0,062 |
| ws2 / ws3 (media 2-3 días) | +0,01/+0,01 | +0,04/+0,02 | 7/8 · 6/8 | +0,049/+0,040 |
| wi1/wi2/wi3 (mecha inferior) | ≈0 | ≈0 | 3-6/8 | ≈0 |

- **Compresión de volatilidad: NO SIRVE** — ninguna métrica separa (lo mejor
  comp3_atr con ρ −0,03 y parcial +0,02: nada).
- **Mecha inferior: NO SIRVE.**
- **Mecha superior víspera: señal DÉBIL de universo**: deciles monótonos, del
  2.º decil (fade 25,4 %) al 10.º (31,4 %) — víspera con mecha superior grande
  (rechazo arriba) → al día siguiente el gap se desinfla ~6 pp más. Parcial
  +0,067: añade margen sobre 1.6/3.2/6.1, pero de tamaño modesto.

## Resultados — trades reales

- **1B (4.482 trades 2024-26): PLANO/RUIDO.** ws1: ρ +0,020/−0,008/+0,034 por
  año, parcial +0,011; mitades por mediana cruzan el signo (2024 bajo-mejor
  +2,86 vs +1,53; 2026 invertido +3,57 vs +4,54); deciles en zigzag. Igual
  wsc1. Como ya pasó con 5.2: descriptor del día que la 1B no puede cobrar
  (entra demasiado pronto).
- **2B (1.656 trades 2024-26, fade tarde): INCONSISTENTE.** ρ
  −0,013/+0,023/+0,085 por año; mitades 2024 al revés (+3,99 bajo vs +2,40
  alto), 2025 plano, 2026 sí. Quintiles no monótonos. No vale.

## Conclusión

**Bloque 8 cerrado SIN construcción.** La compresión de volatilidad y las
mechas inferiores no separan nada; la mecha superior de la víspera es un
descriptor de universo débil (7/8 años, +6 pp de fade entre extremos) que no
se traduce en trades de la 1B ni de la 2B — mismo patrón que 5.2 (la forma del
día la cobra un fade tarde, pero ni la 2B actual lo capta). No aporta sobre
1.6/3.2/6.1 en trades. Sin ✅ a nivel de estrategia → nada que verificar a
mano a nivel de trades (las features sí: 6/6 idénticas) ni que llevar a
cartera. Registrado todo, incluidos los descartes.
