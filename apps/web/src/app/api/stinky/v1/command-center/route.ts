import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API_BASE = (process.env.STINKY_API_URL || "http://127.0.0.1:8010").replace(/\/$/, "");
const UPSTREAM_PATH = "/v1/command-center";
const TIMEOUT_MS = 20_000;
const RETRY_DELAY_MS = 250;
const RETRYABLE_STATUS = new Set([502, 503, 504]);

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function elapsedMs(startedAt: number) {
  return Date.now() - startedAt;
}

function diagnosticHeaders(
  kind: string,
  attempt: number,
  durationMs: number,
  upstreamStatus?: number,
) {
  const headers = new Headers();
  headers.set("Cache-Control", "no-store");
  headers.set("X-Genesis-Upstream", UPSTREAM_PATH);
  headers.set("X-Genesis-Failure-Kind", kind);
  headers.set("X-Genesis-Attempt", String(attempt));
  headers.set("X-Genesis-Duration-Ms", String(durationMs));
  if (upstreamStatus != null) {
    headers.set("X-Genesis-Upstream-Status", String(upstreamStatus));
  }
  return headers;
}

function logFailure(details: Record<string, unknown>) {
  console.warn("command_center.refresh_failure", JSON.stringify(details));
}

export async function GET() {
  for (let attempt = 1; attempt <= 2; attempt += 1) {
    const startedAt = Date.now();
    try {
      const response = await fetch(`${API_BASE}${UPSTREAM_PATH}`, {
        method: "GET",
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: AbortSignal.timeout(TIMEOUT_MS),
      });
      const durationMs = elapsedMs(startedAt);

      if (RETRYABLE_STATUS.has(response.status) && attempt === 1) {
        logFailure({
          endpoint: UPSTREAM_PATH,
          failure_kind: "upstream_http",
          upstream_status: response.status,
          attempt,
          duration_ms: durationMs,
          retrying: true,
        });
        await sleep(RETRY_DELAY_MS);
        continue;
      }

      const body = await response.arrayBuffer();
      const headers = new Headers();
      headers.set("Cache-Control", "no-store");
      headers.set("Content-Type", response.headers.get("Content-Type") || "application/json");
      headers.set("X-Genesis-Upstream", UPSTREAM_PATH);
      headers.set("X-Genesis-Attempt", String(attempt));
      headers.set("X-Genesis-Duration-Ms", String(durationMs));
      headers.set("X-Genesis-Upstream-Status", String(response.status));

      if (!response.ok) {
        logFailure({
          endpoint: UPSTREAM_PATH,
          failure_kind: "upstream_http",
          upstream_status: response.status,
          attempt,
          duration_ms: durationMs,
          retrying: false,
        });
      }

      return new NextResponse(body, { status: response.status, headers });
    } catch (error) {
      const durationMs = elapsedMs(startedAt);
      const timeout = error instanceof DOMException && error.name === "TimeoutError";
      const kind = timeout ? "timeout" : "transport";
      const message = error instanceof Error ? error.message : String(error);

      if (attempt === 1) {
        logFailure({
          endpoint: UPSTREAM_PATH,
          failure_kind: kind,
          attempt,
          duration_ms: durationMs,
          retrying: true,
          error: message.slice(0, 200),
        });
        await sleep(RETRY_DELAY_MS);
        continue;
      }

      logFailure({
        endpoint: UPSTREAM_PATH,
        failure_kind: kind,
        attempt,
        duration_ms: durationMs,
        retrying: false,
        error: message.slice(0, 200),
      });

      return NextResponse.json(
        {
          detail: "Command Center upstream refresh failed",
          endpoint: UPSTREAM_PATH,
          failure_kind: kind,
          attempt,
          duration_ms: durationMs,
        },
        {
          status: timeout ? 504 : 502,
          headers: diagnosticHeaders(kind, attempt, durationMs),
        },
      );
    }
  }

  return NextResponse.json(
    { detail: "Command Center upstream refresh failed", endpoint: UPSTREAM_PATH },
    { status: 502 },
  );
}
