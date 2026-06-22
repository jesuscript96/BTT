import { describe, it, expect } from "vitest";
import { loadConfig } from "../src/config.js";

describe("config", () => {
  it("defaults api base and strips trailing slash", () => {
    const c = loadConfig({ EDGECUTE_API_BASE: "https://x.test/v1/" } as NodeJS.ProcessEnv);
    expect(c.apiBase).toBe("https://x.test/v1");
  });
  it("reads api key", () => {
    const c = loadConfig({ EDGECUTE_API_KEY: "ek_test_abc" } as NodeJS.ProcessEnv);
    expect(c.apiKey).toBe("ek_test_abc");
  });
});
