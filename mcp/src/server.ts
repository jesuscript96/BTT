/** Builds the Edgecute MCP server: build-time tools (codegen, component library,
 *  validation) + resources (docs/schema/templates) + prompts. */
import { promises as fs } from "node:fs";
import { dirname, isAbsolute, relative, resolve } from "node:path";

import { McpServer, ResourceTemplate } from "@modelcontextprotocol/sdk/server/mcp.js";
import { z } from "zod";

import { EdgecuteClient, EdgecuteApiError } from "./client.js";
import { loadConfig, type EdgecuteConfig } from "./config.js";
import { COMPONENTS, getComponent, listComponents, MODULES } from "./components.js";
import { generateApiClientFiles, generateTypes } from "./codegen.js";
import { scaffoldComponent } from "./scaffold.js";
import { listRecipes } from "./recipes.js";
import { GETTING_STARTED, METRICS_GLOSSARY, STRATEGY_SCHEMA_NOTE } from "./docs.js";

type ToolResult = { content: Array<{ type: "text"; text: string }>; isError?: boolean };

function ok(result: unknown): ToolResult {
  return { content: [{ type: "text", text: JSON.stringify({ ok: true, result }, null, 2) }] };
}

function fail(error: string): ToolResult {
  return { content: [{ type: "text", text: JSON.stringify({ ok: false, error }) }], isError: true };
}

function asError(err: unknown): string {
  if (err instanceof EdgecuteApiError) return `${err.message} (code=${err.code}, status=${err.status})`;
  if (err instanceof Error) return err.message;
  return String(err);
}

async function writeFiles(files: Array<{ path: string; content: string }>): Promise<string[]> {
  const written: string[] = [];
  for (const f of files) {
    const abs = resolve(process.cwd(), f.path);
    const rel = relative(process.cwd(), abs);
    if (rel.startsWith("..") || isAbsolute(rel)) {
      throw new Error(`Ruta fuera del proyecto: ${f.path}`);
    }
    await fs.mkdir(dirname(abs), { recursive: true });
    await fs.writeFile(abs, f.content, "utf8");
    written.push(f.path);
  }
  return written;
}

export function buildServer(cfg: EdgecuteConfig = loadConfig()): McpServer {
  const client = new EdgecuteClient({ apiBase: cfg.apiBase, apiKey: cfg.apiKey });
  const server = new McpServer({ name: "edgecute-mcp", version: "0.1.0" });

  // ── Tools: discovery ───────────────────────────────────────────────────────
  server.registerTool(
    "list_modules",
    { title: "List modules", description: "Lista los módulos del producto disponibles vía el MCP." },
    async () => ok({ modules: MODULES }),
  );

  server.registerTool(
    "list_components",
    {
      title: "List components",
      description: "Lista los componentes de resultado escogibles (cada uno con el include de datos que necesita).",
      inputSchema: { module: z.string().optional() },
    },
    async ({ module }) =>
      ok({
        components: listComponents(module).map((c) => ({
          id: c.id, module: c.module, title: c.title, description: c.description,
          include: c.include, peerDeps: c.peerDeps,
        })),
      }),
  );

  // ── Tools: codegen / scaffolding ───────────────────────────────────────────
  server.registerTool(
    "add_component",
    {
      title: "Add component",
      description: "Escribe en tu proyecto UN componente de resultado (gráfica o métricas concretas).",
      inputSchema: {
        component: z.string().describe("id del componente (ver list_components)"),
        targetDir: z.string().optional(),
        componentName: z.string().optional(),
        write: z.boolean().optional().describe("Escribir a disco (default true)"),
      },
    },
    async ({ component, targetDir, componentName, write }) => {
      try {
        const opts: { targetDir?: string; componentName?: string } = {};
        if (targetDir !== undefined) opts.targetDir = targetDir;
        if (componentName !== undefined) opts.componentName = componentName;
        const res = scaffoldComponent(component, opts);
        const written = write === false ? [] : await writeFiles(res.files);
        return ok({
          component: res.componentId, componentName: res.componentName,
          files: res.files.map((f) => f.path), written,
          include: res.include, peerDeps: res.peerDeps, instructions: res.instructions,
          ...(write === false ? { contents: res.files } : {}),
        });
      } catch (err) {
        return fail(asError(err));
      }
    },
  );

  server.registerTool(
    "generate_api_client",
    {
      title: "Generate API client",
      description: "Genera un cliente tipado de la API (TypeScript) en tu proyecto.",
      inputSchema: { targetDir: z.string().optional(), write: z.boolean().optional() },
    },
    async ({ targetDir, write }) => {
      try {
        const gen = generateApiClientFiles(targetDir ?? "src/lib/edgecute");
        const written = write === false ? [] : await writeFiles(gen.files);
        return ok({
          files: gen.files.map((f) => f.path), written, instructions: gen.instructions,
          ...(write === false ? { contents: gen.files } : {}),
        });
      } catch (err) {
        return fail(asError(err));
      }
    },
  );

  server.registerTool(
    "get_types",
    { title: "Get types", description: "Devuelve los tipos TypeScript de la API para pegar/importar." },
    async () => ok({ types: generateTypes() }),
  );

  // ── Tools: API-backed (build-time helpers) ────────────────────────────────
  server.registerTool(
    "validate_strategy",
    {
      title: "Validate strategy",
      description: "Valida una estrategia contra el esquema real (sin ejecutar nada).",
      inputSchema: { strategy: z.record(z.string(), z.unknown()) },
    },
    async ({ strategy }) => {
      try {
        return ok(await client.validateStrategy(strategy));
      } catch (err) {
        return fail(asError(err));
      }
    },
  );

  server.registerTool(
    "preview_universe",
    {
      title: "Preview universe",
      description: "Cuántos ticker-días tendría un universo (para presupuestar), sin ejecutar.",
      inputSchema: {
        dataset_ref: z.string().optional(),
        date_from: z.string().optional(),
        date_to: z.string().optional(),
        apply_day: z.enum(["gap_day", "gap_1_day", "gap_2_day"]).optional(),
      },
    },
    async (args) => {
      try {
        return ok(await client.previewUniverse(args));
      } catch (err) {
        return fail(asError(err));
      }
    },
  );

  server.registerTool(
    "run_sample_backtest",
    {
      title: "Run sample backtest (dev only)",
      description: "Ejecuta un backtest pequeño contra el sandbox para ver datos reales mientras construyes. Requiere una API key ek_test_.",
      inputSchema: {
        strategy: z.record(z.string(), z.unknown()),
        dataset_ref: z.string().optional(),
        include: z.array(z.enum(["metrics", "equity", "days", "trades"])).optional(),
      },
    },
    async ({ strategy, dataset_ref, include }) => {
      if (!client.hasKey()) return fail("Falta EDGECUTE_API_KEY en el entorno del MCP.");
      if (!client.isTestKey()) {
        return fail("run_sample_backtest es dev-only: usa una API key de sandbox (ek_test_).");
      }
      try {
        const body = {
          universe: { dataset_ref: dataset_ref ?? "mock_dataset_1" },
          strategy,
          include: include ?? ["metrics", "equity"],
        };
        return ok(await client.runBacktest(body));
      } catch (err) {
        return fail(asError(err));
      }
    },
  );

  server.registerTool(
    "list_recipes",
    {
      title: "List recipes",
      description: "Recetas de estrategia + dashboard listas para scaffolding.",
      inputSchema: { tag: z.string().optional() },
    },
    async ({ tag }) => ok({ recipes: listRecipes(tag) }),
  );

  // ── Resources: docs ────────────────────────────────────────────────────────
  const docResource = (uri: string, name: string, text: string) =>
    server.registerResource(name, uri, { mimeType: "text/markdown" }, async (u) => ({
      contents: [{ uri: u.href, text }],
    }));

  docResource("docs://getting-started", "getting-started", GETTING_STARTED);
  docResource("docs://metrics-glossary", "metrics-glossary", METRICS_GLOSSARY);
  docResource("docs://strategy-schema", "strategy-schema", STRATEGY_SCHEMA_NOTE);

  // schema://openapi — live OpenAPI from the API (needs a key).
  server.registerResource(
    "openapi",
    "schema://openapi",
    { mimeType: "application/json" },
    async (u) => {
      try {
        const schema = await client.fetchOpenApi();
        return { contents: [{ uri: u.href, text: JSON.stringify(schema, null, 2) }] };
      } catch (err) {
        return { contents: [{ uri: u.href, text: JSON.stringify({ error: asError(err) }) }] };
      }
    },
  );

  // templates://backtest/{component} — the TSX of each component.
  server.registerResource(
    "component-template",
    new ResourceTemplate("templates://backtest/{component}", { list: undefined }),
    { mimeType: "text/plain" },
    async (u, vars) => {
      const id = String(vars.component);
      const spec = getComponent(id);
      const text = spec
        ? spec.render({})
        : `// Componente desconocido '${id}'. Disponibles: ${COMPONENTS.map((c) => c.id).join(", ")}`;
      return { contents: [{ uri: u.href, text }] };
    },
  );

  // ── Prompts ────────────────────────────────────────────────────────────────
  server.registerPrompt(
    "design_strategy",
    { title: "Design a strategy", description: "Guía para construir una Strategy válida paso a paso." },
    () => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              "Ayúdame a diseñar una estrategia de backtest válida para la Edgecute API. " +
              "1) Pregúntame bias (long/short) y la idea. 2) Usa list_indicators para nombres válidos. " +
              "3) Construye el objeto Strategy (ver docs://strategy-schema). 4) Valídalo con validate_strategy " +
              "y corrige hasta que sea válido.",
          },
        },
      ],
    }),
  );

  server.registerPrompt(
    "build_dashboard",
    {
      title: "Build a results dashboard",
      description: "Andamia un dashboard con los componentes elegidos.",
      argsSchema: { components: z.string().optional() },
    },
    ({ components }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              "Monta un dashboard de resultados de backtest. Pasos: 1) generate_api_client. " +
              `2) add_component para cada pieza (${components ?? "p.ej. equity-chart, metrics-grid, trades-table"}). ` +
              "3) Cablea cada componente con su sección include. 4) Usa run_sample_backtest para ver datos reales.",
          },
        },
      ],
    }),
  );

  server.registerPrompt(
    "analyze_results",
    {
      title: "Analyze backtest results",
      description: "Interpreta aggregate_metrics de un backtest.",
      argsSchema: { job_id: z.string().optional() },
    },
    ({ job_id }) => ({
      messages: [
        {
          role: "user",
          content: {
            type: "text",
            text:
              `Interpreta las métricas del backtest ${job_id ?? "(usa el job_id)"}. ` +
              "Consulta docs://metrics-glossary. Evalúa expectancy, drawdown, Sharpe/Sortino, " +
              "win rate vs payoff, y si hay señales de overfitting.",
          },
        },
      ],
    }),
  );

  return server;
}
