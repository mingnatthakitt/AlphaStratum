import { NextRequest, NextResponse } from "next/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
const AUTH_KEY = process.env.AUTH_KEY || "";

// Headers we refuse to forward. These come from the browser and would either
// break the upstream request or leak session state to a different service.
const SKIP_REQUEST_HEADERS = new Set([
  "host",
  "connection",
  "content-length",
  "cookie",
  "set-cookie",
  "transfer-encoding",
  "upgrade",
]);

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

function buildUpstreamUrl(req: NextRequest, pathSegments: string[]): URL {
  const url = new URL(`${API_URL}/${pathSegments.join("/")}`);
  // Server-side auth — always the server key, never caller-supplied.
  url.searchParams.set("key", AUTH_KEY);
  // Forward caller query params (skip any caller-supplied `key` to prevent override).
  req.nextUrl.searchParams.forEach((value, key) => {
    if (key === "key") return;
    url.searchParams.set(key, value);
  });
  return url;
}

async function proxyRequest(req: NextRequest, pathSegments: string[]): Promise<NextResponse> {
  const url = buildUpstreamUrl(req, pathSegments);

  const isJsonBody = req.method === "POST" || req.method === "PUT" || req.method === "PATCH";
  const headers = buildUpstreamHeaders(req, isJsonBody ? "application/json" : undefined);

  const init: RequestInit = {
    method: req.method,
    headers,
    // 25s hard cap — Vercel hobby timeout is 10s, pro is 60s; stay under both.
    signal: AbortSignal.timeout(25_000),
  };

  if (isJsonBody) {
    const body = await req.text();
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
  const isJson = contentType.includes("application/json");

  if (isJson) {
    try {
      const data = rawBody.length > 0 ? JSON.parse(rawBody) : {};
      return NextResponse.json(data, { status: response.status });
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
