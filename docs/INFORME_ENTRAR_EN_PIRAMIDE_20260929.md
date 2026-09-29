# Informe — Estudio «Entrar solo en la pirámide» (2026-09-29)

> Problema real de operativa planteado por Álvaro: si en la entrada inicial los
> LOCATES están caros y no entramos, ¿merece la pena entrar en el momento del
> AÑADIDO si entonces están baratos, con el stop donde lo habría tenido la
> entrada inicial? Sin tocar código.

## Método

- Trades de la 1B (B0, 2024-26) con su `executions[]`: **2.668 trades
  piramidaron** (860/1.065/743 por año; 1 añadido cada uno, a una mediana de
  24 minutos de la entrada inicial).
- Tres versiones por trade, simuladas sobre las velas 1m del lago:
  - **A (completo):** el trade tal cual corre hoy (entrada + añadido).
  - **B (solo entrada inicial):** entra a E0/hora0 y sale con el esquema de la
    1B (parciales 25/50/25 a 08:15/08:30/08:45, SL y EOD de sesión 08:45).
  - **C (solo el añadido):** entra al precio y hora DEL AÑADIDO, stop = el stop
    de la entrada inicial (estructura: PMH+10 %), mismas salidas. Métricas en
    R con la distancia del PROPIO añadido (S − P_add) y en % del camino, win
    rate y % de stops.
- **Simulador validado contra el MOTOR**: sobre 200 trades SIN pirámide (que
  siguen exactamente el esquema B: parciales 25/50/25 + SL + EOD 08:45), el R
  simulado vs el R real del engine da **ΔR mediana 0,0000 · 98 % < 0,05 R ·
  1/200 discrepancias de clasificación SL** (vela que atraviesa el stop justo
  en el borde de un parcial). v1 del simulador tenía DOS bugs (el SL se
  comprobaba tras repartir los parciales → 0 % stops falsos; y el EOD caía a
  las 11:00 por reutilizar las velas del estudio RTH): corregidos antes de
  medir nada.

## Resultados

| año | A completo | B solo inicial | C solo añadido |
|---|---|---|---|
| 2024 (n=860) | +0,24 R · win 75 % | **+0,37 R** · win 77 % · stops 13,4 % | +0,08 R · win 66 % · stops 13,4 % |
| 2025 (n=1.065) | +0,29 R · win 77 % | **+0,41 R** · win 79 % · stops 14,3 % | +0,12 R · win 73 % · stops 14,3 % |
| 2026 (n=743) | +0,32 R · win 79 % | **+0,45 R** · win 81 % · stops 13,1 % | +0,14 R · win 73 % · stops 13,1 % |

- **B > A > C los tres años.** El añadido DILUYE el trade: la entrada inicial
  es ~3× más de R que el añadido (ΔR medio B−C = +0,30; B mejor que C en el
  70 % de los trades).
- **C gana por sí solo, pero poco:** +0,08/+0,12/+0,14 R por trade (win
  66-73 %). No es negativo — es un tercio del edge de la entrada inicial.
- **Tramos de margen del añadido** (aire hasta el stop en el momento de
  entrar; casi todos >20 % porque el stop es PMH+10 %):
  «10-20 %» (n=140): +0,10 R, win 65 %, stops 21 % · «>20 %» (n=2.528):
  +0,11 R, win 71 %, stops 13 %. El margen NO separa (2024 al revés, 2026
  plano; el tramo estrecho para de stops 27 % en 2026 pero la muestra es
  chica). Con el stop de estructura el margen casi nunca es el problema.

## ¿Se puede backtestear C en la app hoy?

**Casi, pero no del todo.** Lo que ya existe:
- **Pirámides como niveles** (`pyramiding.levels[]`): un nivel `add` con sus
  condiciones y `capital_frac` — permite modelar «entra después» pero SIEMPRE
  sobre una entrada inicial que también existe; no hay «solo el segundo
  escalón».
- **SL por lote** (`lot_stop` en cada nivel, PRD 2026-09-15) y **TP por lote**:
  cada lote puede tener su propio stop/objetivo — la pieza de gestión sí está.
- El stop de C (estructura PMH+10 % vigente «como en la entrada inicial») se
  aproxima con `Market Structure (Previous Max)` evaluado EN la vela del
  añadido: da el mismo nivel salvo que el PMH se haya extendido entre medias.

**La pieza que falta:** un modo «entrada condicionada a otra entrada que NO
ocurrió» — es decir, niveles de pirámide ejecutables SIN la entrada madre
(condición del nivel evaluada en solitario, sizing propio, y el stop de
estructura referido al marco que habría tenido la entrada original). Hoy la
palabra «pirámide» exige la entrada primera. No lo he escrito: es una pieza
del motor compartido (misma consideración que la salida programada condicional).

## Sesgo que el backtest NO ve

**Los locates caros no son ruido: correlacionan con riesgo.** Que el locate
esté caro sueleser señal de que el mercado espera SQUEEZE (mucho interés en
comprar el préstamo = presión compradora). El estudio C asume que «entrar en
el añadido con locates baratos» es la misma operación con otro precio de
alquiler — pero los días de locates caros son OTRO régimen de riesgo, y el
histórico que simulamos (velas 1m) no lleva el precio de los locates, así que
C está medido sobre TODOS los añadidos, no solo los de «locates baratos». El
número real de la operativa podría ser PEOR de lo que aquí sale los días en
que el alquiler avisa de squeeze. No tenemos histórico de precio de locates
para filtrar por ello.

## Conclusión

**C gana por sí solo, pero es un tercio de la entrada inicial** (+0,08/+0,12/
+0,14 R vs +0,37/+0,41/+0,45; mismo % de stops porque comparten stop). Como
«plan B cuando los locates impiden la entrada madre» tiene sentido
matemático; como sustituto de la entrada inicial, no (B > A > C los tres
años: el añadido diluye). El margen hasta el stop casi nunca separa (el stop
de estructura deja >20 % de aire en el 95 % de los casos). Para decidir de
verdad falta el histórico de locates (sesgo de squeeze no medible aquí).
