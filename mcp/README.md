# @edgecute/mcp

**Edgecute Backtest MCP** — a **build-time** Model Context Protocol server for traders
building their own local apps in **Cursor / Claude Code**. It helps you *build* the app
(typed API client, result components, docs, validation). At **runtime your app calls the
Edgecute Backtest API directly** — the MCP is not in the hot path.

> Design: `docs/b2d-gateway/04_MCP_TOOLS_RESOURCES.md`.

## Install (in your IDE)

```jsonc
// .cursor/mcp.json  (or Claude Code MCP settings)
{
  "mcpServers": {
    "edgecute": {
      "command": "npx",
      "args": ["-y", "@edgecute/mcp"],
      "env": {
        "EDGECUTE_API_KEY": "ek_test_…",        // sandbox key for building
        "EDGECUTE_API_BASE": "https://api.edgecute.com/v1"
      }
    }
  }
}
```

## What it gives you

### Tools
| Tool | What it does |
|---|---|
| `list_modules` | Product modules exposed via the MCP (MVP: `backtest`). |
| `list_components` | The result components you can scaffold + the `include` each needs. |
| `add_component` | Writes ONE component (a chart or specific metrics) into your project. |
| `generate_api_client` | Emits a typed TS client for the API into your project. |
| `get_types` | Returns the API TypeScript types. |
| `validate_strategy` | Validates a strategy against the real schema (no run). |
| `preview_universe` | How many ticker-days a universe would cost (no run). |
| `run_sample_backtest` | **Dev-only** small backtest vs the sandbox (`ek_test_` required). |
| `list_recipes` | Ready-made strategy + dashboard recipes. |

### Resources
- `docs://getting-started`, `docs://metrics-glossary`, `docs://strategy-schema`
- `schema://openapi` — the live OpenAPI of the API
- `templates://backtest/{component}` — the TSX of any component

### Prompts
- `design_strategy`, `build_dashboard`, `analyze_results`

## Submodularization (pick only what you render)

Each result piece is a separate component, and **choosing a component decides which data
your app fetches** (`include`). Want just the Sharpe? Add `metric-card`/`metrics-grid` and
request `include=["metrics"]` — nothing else is downloaded. Available components:
`equity-chart`, `drawdown-chart`, `metric-card`, `metrics-grid`, `trades-table`,
`day-results-table`.

## Develop

```bash
npm install
npm run build        # tsc -> dist/
npm test             # vitest (unit + logic)
node scripts/smoke-e2e.mjs   # real MCP client over stdio (no API needed)
```

## Runtime example (your app)

```ts
import { EdgecuteClient } from "./lib/edgecute/edgecuteClient";   // from generate_api_client
const c = new EdgecuteClient({ apiKey: process.env.EDGECUTE_API_KEY! });
const job = await c.runBacktest({
  universe: { dataset_ref: "ds_123", date_from: "2024-01-01", date_to: "2024-03-31" },
  strategy: {/* validated with validate_strategy */},
  include: ["metrics", "equity"],     // only what you render
});
// <EquityChart data={job.result!.global_equity!} />
```
