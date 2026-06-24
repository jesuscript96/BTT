// End-to-end smoke: a real MCP client connects to the built server over stdio,
// lists tools/resources/prompts and calls a build-time tool (no API needed).
// Run: node scripts/smoke-e2e.mjs
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";

const transport = new StdioClientTransport({
  command: "node",
  args: ["dist/index.js"],
  env: { ...process.env, EDGECUTE_API_KEY: "ek_test_smoke" },
});

const client = new Client({ name: "smoke", version: "1.0.0" });
await client.connect(transport);

const tools = await client.listTools();
const resources = await client.listResources();
const templates = await client.listResourceTemplates().catch(() => ({ resourceTemplates: [] }));
const prompts = await client.listPrompts();

console.log("TOOLS:", tools.tools.map((t) => t.name).join(", "));
console.log("RESOURCES:", resources.resources.map((r) => r.uri).join(", "));
console.log("RESOURCE TEMPLATES:", (templates.resourceTemplates ?? []).map((r) => r.uriTemplate).join(", "));
console.log("PROMPTS:", prompts.prompts.map((p) => p.name).join(", "));

const lc = await client.callTool({ name: "list_components", arguments: {} });
const parsed = JSON.parse(lc.content[0].text);
console.log("list_components ok:", parsed.ok, "| n=", parsed.result.components.length);

const gc = await client.callTool({ name: "add_component", arguments: { component: "equity-chart", write: false } });
const gcParsed = JSON.parse(gc.content[0].text);
console.log("add_component(write=false) ok:", gcParsed.ok, "| include:", JSON.stringify(gcParsed.result.include));

const doc = await client.readResource({ uri: "docs://getting-started" });
console.log("read docs://getting-started bytes:", doc.contents[0].text.length);

await client.close();
console.log("E2E OK");
