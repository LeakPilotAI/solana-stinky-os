import { NextResponse } from "next/server";
import { parseExecutionV2 } from "@/lib/api/intelligence-execution-v2";

export const dynamic = "force-dynamic";
const API_BASE = (process.env.STINKY_API_URL || "http://127.0.0.1:8010").replace(/\/$/, "");

export async function GET() {
  try {
    const response = await fetch(`${API_BASE}/v1/intelligence/execution-v2`, {
      method: "GET", headers: { Accept: "application/json" }, cache: "no-store",
      signal: AbortSignal.timeout(6_000),
    });
    if (!response.ok) throw new Error("Upstream unavailable");
    return NextResponse.json(parseExecutionV2(await response.json()), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ status: "UNKNOWN" }, { status: 502, headers: { "Cache-Control": "no-store" } });
  }
}
