# 03 — Contrato de Datos

Este documento define la estructura de intercambio de datos JSON para la nueva funcionalidad del Ticker Analysis y el Asistente Edgie.

---

## 1. Extensiones al Endpoint `/api/ticker-analysis/{ticker}/balance-sheet`

Para alimentar la nueva pestaña "Balance" de la UI, se amplía la respuesta del backend para incluir el histórico de patrimonio neto (`equity`) y de acciones en circulación (`shares_outstanding`) obtenido del balance trimestral.

### 1.1 Response JSON de Balance Sheet Ampliado
```json
{
  "charts": {
    "cash_history": [
      { "date": "2025-12-31", "value": 12500000.00 },
      { "date": "2026-03-31", "value": 8200000.00 }
    ],
    "debt_history": [
      { "date": "2025-12-31", "value": 1500000.00 },
      { "date": "2026-03-31", "value": 2000000.00 }
    ],
    "working_capital_history": [
      { "date": "2025-12-31", "value": 11000000.00 },
      { "date": "2026-03-31", "value": 6200000.00 }
    ],
    "equity_history": [
      { "date": "2025-12-31", "value": 15000000.00 },
      { "date": "2026-03-31", "value": 13200000.00 }
    ],
    "shares_outstanding_history": [
      { "date": "2025-12-31", "value": 42000000.00 },
      { "date": "2026-03-31", "value": 55000000.00 }
    ]
  },
  "working_capital": 6200000.00
}
```

---

## 2. Contrato de Respuesta de Edgie AI (`<edgie_metrics>`)

Se modifica la estructura JSON que Edgie AI devuelve dentro de los tags XML `<edgie_metrics>...</edgie_metrics>` para incorporar la información estructurada de ownership, warrants, y cumplimiento Nasdaq.

### 2.1 Schema JSON de `<edgie_metrics>`
```json
{
  "dilution_rating": "LOW" | "MEDIUM" | "HIGH" | "CRITICAL",
  "dilution_score": 75,
  "cash_runway_months": 5.4,
  "float_percentage": 12.5,
  "runner_assessment": "FADER" | "SQUEEZE" | "NEUTRAL",
  "shelf_capacity_usd": 25000000.00,
  "pending_s1": false,
  "active_atm_usd": 50000000.00,
  "hired_banks": ["H.C. Wainwright", "Maxim Group"],
  "ownership_list": [
    {
      "name": "Jane Doe",
      "type": "PERSON",
      "percentage": 5.4,
      "details": "Compró 300,000 acciones en mercado abierto",
      "source": "Form 4",
      "date": "2026-06-15"
    },
    {
      "name": "Sabby Capital LLC",
      "type": "INSTITUTION",
      "percentage": 8.2,
      "details": "Posee participación de fondo",
      "source": "Schedule 13G",
      "date": "2026-02-14"
    }
  ],
  "warrants_triggers": [
    {
      "type": "EXERCISE",
      "price": 5.00,
      "shares": 10000000,
      "notes": "10M warrants ejercibles a $5.00 (Techo de peligro)"
    },
    {
      "type": "REDEMPTION",
      "price": 7.50,
      "shares": null,
      "notes": "Cláusula de rescate si cotiza > $7.50 durante 10 días"
    }
  ],
  "nasdaq_compliance": {
    "below_one_dollar_days": 15,
    "below_ten_cents_days": 0,
    "equity_usd": 2200000.00,
    "market_cap_usd": 32000000.00,
    "compliance_risk": "WARNING"
  }
}
```

---

## 3. Modelo de Datos para la Base de Datos de Bancos Dilusores

El backend guardará los bancos extraídos en DuckDB.

### 3.1 Contrato del Registro de Bancos (`dilution_banks_registry`)
*   `ticker`: `VARCHAR` (Clave de ticker, ej: "MULN")
*   `bank_name`: `VARCHAR` (Nombre normalizado del agente dilusor, ej: "MAXIM GROUP")
*   `form_type`: `VARCHAR` (Formulario de donde se extrajo, ej: "S-1")
*   `date_filed`: `DATE` (Fecha de presentación de la SEC)
*   `timestamp`: `TIMESTAMP` (Fecha de inserción en el sistema)

---

## 4. Contrato de la Herramienta Global del Asistente (`ticker.get_analysis`)

Para permitir que Edgie consulte la información de Ticker Analysis en cualquier momento, se define la siguiente herramienta de función (*Tool*):

### 4.1 Schema de Parámetros (JSON Schema)
```json
{
  "name": "ticker_get_analysis",
  "description": "Obtiene la información completa de análisis de un ticker (métricas financieras, gap stats, balance sheet, recientes SEC filings y noticias) para realizar una evaluación de dilución o responder dudas del ticker.",
  "parameters": {
    "type": "object",
    "properties": {
      "ticker": {
        "type": "string",
        "description": "Símbolo de la acción (ej: AAPL, MULN)"
      }
    },
    "required": ["ticker"]
  }
}
```

### 4.2 Esquema de Respuesta de la Herramienta (Retorno al LLM)
```json
{
  "ok": true,
  "result": {
    "ticker": "MULN",
    "profile": { "name": "Mullen Automotive, Inc.", "sector": "Consumer Cyclical", "industry": "Auto Manufacturers" },
    "market": { "price": 0.12, "market_cap": 8400000.0, "shares_outstanding": 70000000, "float_shares": 65000000 },
    "financials": { "cash": 2200000.0, "total_debt": 15000000.0, "working_capital": -12800000.0 },
    "gap_stats": { "gap_days_count": 42, "high_rth_spike_avg": 35.5, "neg_close_freq": 82.1 },
    "filings": { "financials": [ { "type": "10-Q", "title": "Quarterly Report", "date": "2026-05-15", "link": "https://..." } ], "prospectuses": [], "news": [], "ownership": [], "proxies": [], "others": [] },
    "news": [ { "title": "Mullen announces dilution risk", "date": "2026-06-20", "link": "https://..." } ]
  }
}
```

