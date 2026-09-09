import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const API_BASE = (process.env.STINKY_API_URL || "http://127.0.0.1:8010").replace(/\/$/, "");
const UPSTREAM_PATH = "/v1/command-center";
const TIMEOUT_MS = 20_000;
const RETRY_DELAY_MS = 250;
const RETRYABLE_STATUS = new Set([502, 503, 504]);
const PROBE_TIMEOUT_MS = 2_500;

const LATENCY_PROBES = [
  ["health", "/health"],
  ["runners", "/v1/runners?limit=20&min_fees_sol=1&min_volume_m5_usd=33000&pump_only=true"],
  ["alerts", "/v1/alerts?limit=20"],
  ["entities", "/v1/entities?limit=10"],
  ["wallets", "/v1/wallets/smart?limit=15"],
  ["trending", "/v1/trending?min_volume_usd=33000&min_fees_sol=1&limit=25"],
] as const;

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

async function probeEndpoint(section: string, path: string) {
  const startedAt = Date.now();
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
    });
    const durationMs = elapsedMs(startedAt);
    console.warn(
      "command_center.latency_probe",
      JSON.stringify({
        section,
        endpoint: path,
        ok: response.ok,
        upstream_status: response.status,
        duration_ms: durationMs,
      }),
    );
    try {
      await response.body?.cancel();
    } catch {
      // Probe response body is intentionally discarded.
    }
  } catch (error) {
    const durationMs = elapsedMs(startedAt);
    const timeout = error instanceof DOMException && error.name === "TimeoutError";
    console.warn(
      "command_center.latency_probe",
      JSON.stringify({
        section,
        endpoint: path,
        ok: false,
        failure_kind: timeout ? "timeout" : "transport",
        duration_ms: durationMs,
        error: (error instanceof Error ? error.message : String(error)).slice(0, 160),
      }),
    );
  }
}

async function runLatencyProbes() {
  const startedAt = Date.now();
  await Promise.all(LATENCY_PROBES.map(([section, path]) => probeEndpoint(section, path)));
  console.warn(
    "command_center.latency_probe_batch",
    JSON.stringify({
      sections: LATENCY_PROBES.length,
      duration_ms: elapsedMs(startedAt),
      reason: "command_center_final_refresh_failure",
    }),
  );
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
        if (attempt === 2 && RETRYABLE_STATUS.has(response.status)) {
          await runLatencyProbes();
        }
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
      await runLatencyProbes();

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
