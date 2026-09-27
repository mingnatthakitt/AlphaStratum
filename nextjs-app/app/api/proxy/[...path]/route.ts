import { NextRequest, NextResponse } from "next/server";

// Read lazily (not at module load) so runtime env changes and tests work.
function apiUrl(): string {
  return process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
}

function authKey(): string {
  return process.env.AUTH_KEY || "";
}

/**
 * Server-side proxy to the FastAPI backend.
 * - Attaches the shared auth key as an `X-Auth-Key` header (server-only env
 *   var, never in the bundle). A header rather than `?key=` so the secret does
 *   not land in uvicorn access logs, proxy/CDN logs or browser history.
 * - Allowlists backend prefixes so browser calls can't reach admin/management
 *   routes (e.g. /models/cache/purge) through this proxy.
 * - Buffers JSON responses (no SSE/streaming endpoints exist yet).
 */

// Only these backend routers are reachable from the browser.
const ALLOWED_PREFIXES = ["fetch/", "models/", "rag/", "portfolio/"];
// Management/ops routes that must not be callable through the site.
const BLOCKED_SEGMENTS = ["cache/purge", "cache/stats"];

const SKIP_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "cookie",
  "set-cookie",
  "transfer-encoding",
  "upgrade",
  "x-forwarded-host",
  "x-forwarded-proto",
  // A caller must never be able to supply or override the shared secret.
  "x-auth-key",
]);

// The body is buffered into memory before forwarding, so cap it. The largest
// legitimate request is a chat message, which the backend caps at 2000 chars.
const MAX_BODY_BYTES = 64 * 1024;

function buildUpstreamHeaders(req: NextRequest, forceContentType?: string): Headers {
  const out = new Headers();
  if (forceContentType) out.set("Content-Type", forceContentType);
  req.headers.forEach((value, key) => {
    const lower = key.toLowerCase();
    if (SKIP_REQUEST_HEADERS.has(lower)) return;
    if (forceContentType && lower === "content-type") return; // never let caller override our forced type
    out.set(key, value);
  });
  return out;
}

function isAllowedPath(pathSegments: string[]): boolean {
  // Reject traversal attempts before URL normalization could resolve them.
  if (pathSegments.some((seg) => seg === "." || seg === "..")) return false;
  const joined = pathSegments.join("/").toLowerCase();
  if (!ALLOWED_PREFIXES.some((prefix) => joined.startsWith(prefix))) return false;
  if (BLOCKED_SEGMENTS.some((segment) => joined.includes(segment))) return false;
  return true;
}

function buildUpstreamUrl(req: NextRequest, pathSegments: string[]): URL {
  const url = new URL(`${apiUrl()}/${pathSegments.map(encodeURIComponent).join("/")}`);
  // Forward caller query params (skip any caller-supplied `key` to prevent
  // override — the server key now travels in a header, never the query string).
  req.nextUrl.searchParams.forEach((value, key) => {
    if (key === "key") return;
    url.searchParams.set(key, value);
  });
  return url;
}

function upstreamTimeoutMs(pathSegments: string[]): number {
  const joined = pathSegments.join("/").toLowerCase();
  // LLM chat and the cold screener legitimately need longer than the default;
  // everything else aborts quickly so the UI fails fast.
  if (joined.startsWith("rag/chat")) return 90_000;
  if (joined.startsWith("fetch/screener")) return 45_000;
  return 25_000;
}

async function proxyRequest(req: NextRequest, pathSegments: string[]): Promise<NextResponse> {
  if (!isAllowedPath(pathSegments)) {
    return NextResponse.json({ detail: "Path not allowed" }, { status: 403 });
  }

  const url = buildUpstreamUrl(req, pathSegments);

  const isJsonBody = req.method === "POST" || req.method === "PUT" || req.method === "PATCH";
  const headers = buildUpstreamHeaders(req, isJsonBody ? "application/json" : undefined);
  // Always the server's own key, attached after the allowlist check passes.
  headers.set("X-Auth-Key", authKey());

  const init: RequestInit = {
    method: req.method,
    headers,
    // Abort long-hanging upstream calls. Note: serverless platforms enforce
    // their own (often shorter) function timeout — see LIMITATIONS.md.
    signal: AbortSignal.timeout(upstreamTimeoutMs(pathSegments)),
  };

  if (isJsonBody) {
    // Reject oversized bodies before buffering them.
    const declared = Number(req.headers.get("content-length") ?? "");
    if (Number.isFinite(declared) && declared > MAX_BODY_BYTES) {
      return NextResponse.json({ detail: "Request body too large" }, { status: 413 });
    }
    const body = await req.text();
    if (body.length > MAX_BODY_BYTES) {
      return NextResponse.json({ detail: "Request body too large" }, { status: 413 });
    }
    if (body.length > 0) init.body = body;
  }

  let response: Response;
  try {
    response = await fetch(url, init);
  } catch (err) {
    const msg = err instanceof Error ? err.message : "upstream fetch failed";
    return NextResponse.json({ detail: "Upstream unreachable", error: msg }, { status: 502 });
  }

  // Read body as text first, then try to parse — upstream may return non-JSON on errors.
  const rawBody = await response.text();
  const contentType = response.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    try {
      const data = rawBody.length > 0 ? JSON.parse(rawBody) : {};
      const res = NextResponse.json(data, { status: response.status });
      // Pass caching hints through so the browser can cache proxied data.
      const cacheControl = response.headers.get("cache-control");
      if (cacheControl) res.headers.set("Cache-Control", cacheControl);
      return res;
    } catch {
      // Fall through to text passthrough.
    }
  }
  return new NextResponse(rawBody, {
    status: response.status,
    headers: { "Content-Type": contentType || "text/plain" },
  });
}

export async function GET(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxyRequest(req, params.path);
}

export async function POST(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxyRequest(req, params.path);
}

export async function PUT(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxyRequest(req, params.path);
}

export async function PATCH(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxyRequest(req, params.path);
}

export async function DELETE(req: NextRequest, { params }: { params: { path: string[] } }) {
  return proxyRequest(req, params.path);
}
