import { describe, it, expect } from "vitest";
import { EdgecuteClient, EdgecuteApiError } from "../src/client.js";

interface MockResp {
  status: number;
  body: unknown;
}

function makeFetch(seq: MockResp[]): { fetchImpl: typeof fetch; calls: () => number } {
  let i = 0;
  const fetchImpl = (async () => {
    const r = seq[Math.min(i, seq.length - 1)]!;
    i++;
    return {
      ok: r.status >= 200 && r.status < 300,
      status: r.status,
      json: async () => r.body,
    } as unknown as Response;
  }) as unknown as typeof fetch;
  return { fetchImpl, calls: () => i };
}

const base = { apiBase: "http://x/v1", apiKey: "ek_test_abc", retryBaseMs: 0 };

describe("EdgecuteClient", () => {
  it("returns parsed body on success", async () => {
    const { fetchImpl } = makeFetch([{ status: 200, body: { status: "ok" } }]);
    const c = new EdgecuteClient({ ...base, fetchImpl });
    expect(await c.health()).toEqual({ status: "ok" });
  });

  it("retries on 429 then succeeds", async () => {
    const { fetchImpl, calls } = makeFetch([
      { status: 429, body: { error: { code: "rate_limited", message: "slow" } } },
      { status: 200, body: { status: "ok" } },
    ]);
    const c = new EdgecuteClient({ ...base, fetchImpl, maxRetries: 3 });
    expect(await c.health()).toEqual({ status: "ok" });
    expect(calls()).toBe(2);
  });

  it("retries on 503 up to maxRetries then throws", async () => {
    const { fetchImpl, calls } = makeFetch([{ status: 503, body: { error: { code: "x", message: "down" } } }]);
    const c = new EdgecuteClient({ ...base, fetchImpl, maxRetries: 2 });
    await expect(c.health()).rejects.toBeInstanceOf(EdgecuteApiError);
    expect(calls()).toBe(3); // 1 initial + 2 retries
  });

  it("parses the error envelope (no retry on 422)", async () => {
    const { fetchImpl, calls } = makeFetch([
      { status: 422, body: { error: { code: "invalid_strategy", message: "bad bias" } } },
    ]);
    const c = new EdgecuteClient({ ...base, fetchImpl });
    try {
      await c.validateStrategy({});
      throw new Error("should have thrown");
    } catch (err) {
      expect(err).toBeInstanceOf(EdgecuteApiError);
      const e = err as EdgecuteApiError;
      expect(e.code).toBe("invalid_strategy");
      expect(e.status).toBe(422);
    }
    expect(calls()).toBe(1);
  });

  it("throws unauthorized when no key", async () => {
    const { fetchImpl } = makeFetch([{ status: 200, body: {} }]);
    const c = new EdgecuteClient({ apiBase: "http://x/v1", apiKey: undefined, fetchImpl });
    await expect(c.health()).rejects.toMatchObject({ code: "unauthorized" });
  });

  it("detects test vs live key", () => {
    expect(new EdgecuteClient({ ...base, apiKey: "ek_test_a" }).isTestKey()).toBe(true);
    expect(new EdgecuteClient({ ...base, apiKey: "ek_live_a" }).isTestKey()).toBe(false);
  });
});
