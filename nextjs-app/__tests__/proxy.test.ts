/**
 * Proxy route handler tests: allowlist, auth-key injection, key-override
 * protection, header sanitization, and upstream error handling.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { GET, POST } from "@/app/api/proxy/[...path]/route";

const originalEnv = { ...process.env };

function makeGetRequest(path: string, search = ""): NextRequest {
  return new NextRequest(`http://localhost:3000/api/proxy/${path}${search}`);
}

function makePostRequest(path: string, body: unknown): NextRequest {
  return new NextRequest(`http://localhost:3000/api/proxy/${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_API_URL = "http://backend:8000";
  process.env.AUTH_KEY = "test-secret";
  vi.stubGlobal(
    "fetch",
    vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, data: [1, 2, 3] }), {
        status: 200,
        headers: { "content-type": "application/json", "cache-control": "max-age=60" },
      }),
    ),
  );
});

afterEach(() => {
  process.env = { ...originalEnv };
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("proxy allowlist", () => {
  it("forwards allowed fetch/ paths", async () => {
    const res = await GET(makeGetRequest("fetch/ticker/AAPL"), { params: { path: ["fetch", "ticker", "AAPL"] } });
    expect(res.status).toBe(200);
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
    const url = vi.mocked(fetch).mock.calls[0][0] as URL;
    expect(String(url)).toContain("http://backend:8000/fetch/ticker/AAPL");
  });

  it("rejects non-allowlisted prefixes", async () => {
    const res = await GET(makeGetRequest("admin/panel"), { params: { path: ["admin", "panel"] } });
    expect(res.status).toBe(403);
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });

  it("rejects cache management routes", async () => {
    const res = await POST(makePostRequest("models/cache/purge", {}), {
      params: { path: ["models", "cache", "purge"] },
    });
    expect(res.status).toBe(403);
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });

  it("rejects path traversal segments", async () => {
    const res = await GET(makeGetRequest("fetch/../models"), { params: { path: ["fetch", "..", "models"] } });
    expect(res.status).toBe(403);
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });
});

describe("proxy auth", () => {
  it("attaches the server key as a header, not in the query string", async () => {
    await GET(makeGetRequest("models/regime/AAPL"), { params: { path: ["models", "regime", "AAPL"] } });
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get("X-Auth-Key")).toBe("test-secret");
    // The secret must never reach an access log via the URL.
    const url = vi.mocked(fetch).mock.calls[0][0] as URL;
    expect(url.searchParams.get("key")).toBeNull();
  });

  it("strips a caller-supplied X-Auth-Key header", async () => {
    const req = makeGetRequest("models/regime/AAPL");
    req.headers.set("x-auth-key", "evil");
    await GET(req, { params: { path: ["models", "regime", "AAPL"] } });
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get("X-Auth-Key")).toBe("test-secret");
  });

  it("does not let the caller override the key via the query string", async () => {
    await GET(makeGetRequest("models/regime/AAPL?key=evil"), {
      params: { path: ["models", "regime", "AAPL"] },
    });
    const url = vi.mocked(fetch).mock.calls[0][0] as URL;
    expect(url.searchParams.get("key")).toBeNull();
  });

  it("forwards other query params", async () => {
    await GET(makeGetRequest("models/montecarlo/AAPL?days=90"), {
      params: { path: ["models", "montecarlo", "AAPL"] },
    });
    const url = vi.mocked(fetch).mock.calls[0][0] as URL;
    expect(url.searchParams.get("days")).toBe("90");
  });
});

describe("proxy response handling", () => {
  it("returns JSON with the upstream status and forwards cache headers", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ detail: "nope" }), {
          status: 404,
          headers: { "content-type": "application/json", "cache-control": "no-store" },
        }),
      ),
    );
    const res = await GET(makeGetRequest("fetch/ticker/MISSING"), {
      params: { path: ["fetch", "ticker", "MISSING"] },
    });
    expect(res.status).toBe(404);
    expect(res.headers.get("cache-control")).toBe("no-store");
    const body = await res.json();
    expect(body).toEqual({ detail: "nope" });
  });

  it("maps upstream connection failures to 502", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED"); }));
    const res = await GET(makeGetRequest("fetch/ticker/AAPL"), { params: { path: ["fetch", "ticker", "AAPL"] } });
    expect(res.status).toBe(502);
  });

  it("encodes path segments (symbols like ^GSPC survive)", async () => {
    await GET(makeGetRequest("fetch/ticker/%5EGSPC"), { params: { path: ["fetch", "ticker", "^GSPC"] } });
    const url = vi.mocked(fetch).mock.calls[0][0] as URL;
    expect(url.pathname).toBe("/fetch/ticker/%5EGSPC");
  });

  it("forces content-type on POST bodies", async () => {
    await POST(makePostRequest("rag/chat", { message: "hi" }), { params: { path: ["rag", "chat"] } });
    const init = vi.mocked(fetch).mock.calls[0][1] as RequestInit;
    const headers = init.headers as Headers;
    expect(headers.get("content-type")).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ message: "hi" }));
  });

  it("rejects an oversized body with 413 before calling upstream", async () => {
    // A body far larger than any legitimate request; the proxy buffers it, so
    // it must be capped rather than read into memory unbounded.
    const huge = makePostRequest("rag/chat", { message: "x".repeat(200_000) });
    const res = await POST(huge, { params: { path: ["rag", "chat"] } });
    expect(res.status).toBe(413);
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });

  it("rejects an oversized body declared via content-length", async () => {
    const req = new NextRequest("http://localhost:3000/api/proxy/rag/chat", {
      method: "POST",
      headers: { "content-type": "application/json", "content-length": "999999999" },
      body: JSON.stringify({ message: "hi" }),
    });
    const res = await POST(req, { params: { path: ["rag", "chat"] } });
    expect(res.status).toBe(413);
    expect(vi.mocked(fetch)).not.toHaveBeenCalled();
  });
});
