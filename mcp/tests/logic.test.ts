import { describe, it, expect } from "vitest";
import { COMPONENTS, getComponent, listComponents } from "../src/components.js";
import { scaffoldComponent } from "../src/scaffold.js";
import { generateApiClientFiles, generateTypes } from "../src/codegen.js";
import { listRecipes, getRecipe } from "../src/recipes.js";

describe("component catalog", () => {
  it("has unique ids and the expected backtest pieces", () => {
    const ids = COMPONENTS.map((c) => c.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(ids).toEqual(
      expect.arrayContaining(["equity-chart", "drawdown-chart", "metric-card", "metrics-grid", "trades-table", "day-results-table"]),
    );
  });

  it("filters by module", () => {
    expect(listComponents("backtest").length).toBe(COMPONENTS.length);
    expect(listComponents("nope").length).toBe(0);
  });

  it("each component renders non-empty TSX that references its name", () => {
    for (const c of COMPONENTS) {
      const tsx = c.render({ componentName: "MyThing" });
      expect(tsx.length).toBeGreaterThan(50);
      expect(tsx).toContain("MyThing");
      expect(tsx).toContain("export");
    }
  });
});

describe("scaffoldComponent", () => {
  it("returns a file with the right path and include", () => {
    const res = scaffoldComponent("equity-chart", { targetDir: "src/x", componentName: "Eq" });
    expect(res.files).toHaveLength(1);
    expect(res.files[0]!.path).toBe("src/x/Eq.tsx");
    expect(res.files[0]!.content).toContain("Eq");
    expect(res.include).toEqual(["equity"]);
    expect(res.peerDeps).toContain("lightweight-charts");
  });

  it("sanitizes a bad component name", () => {
    const res = scaffoldComponent("metrics-grid", { componentName: "bad name!!" });
    expect(res.componentName).toBe("badname");
  });

  it("throws an actionable error for an unknown component", () => {
    expect(() => scaffoldComponent("nope")).toThrow(/Disponibles:/);
  });
});

describe("codegen", () => {
  it("emits client + types files", () => {
    const gen = generateApiClientFiles("src/lib/ec");
    const paths = gen.files.map((f) => f.path);
    expect(paths).toEqual(["src/lib/ec/edgecuteTypes.ts", "src/lib/ec/edgecuteClient.ts"]);
    const client = gen.files.find((f) => f.path.endsWith("edgecuteClient.ts"))!.content;
    expect(client).toContain("class EdgecuteClient");
    expect(client).toContain("runBacktest");
    expect(client).toContain("getBacktest");
  });

  it("types include the result shape", () => {
    const t = generateTypes();
    expect(t).toContain("BacktestResult");
    expect(t).toContain("global_equity");
  });
});

describe("recipes", () => {
  it("lists and filters recipes", () => {
    expect(listRecipes().length).toBeGreaterThan(0);
    expect(listRecipes("short").every((r) => r.tags.includes("short"))).toBe(true);
    expect(getRecipe("vwap-fade-short")?.bias ?? getRecipe("vwap-fade-short")?.strategy.bias).toBe("short");
  });
});
