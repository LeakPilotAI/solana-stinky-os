import { NextResponse } from "next/server";
import { parseSupervisor } from "@/lib/api/supervisor-passes";
export const dynamic = "force-dynamic";
const API_BASE = (process.env.STINKY_API_URL || "http://127.0.0.1:8010").replace(/\/$/, "");
export async function GET() {
  try {
    const response = await fetch(`${API_BASE}/v1/intelligence/execution-v2/supervisor-passes`, { method: "GET", cache: "no-store", headers: { Accept: "application/json" }, signal: AbortSignal.timeout(6_000) });
    if (!response.ok) throw new Error("Unavailable");
    return NextResponse.json(parseSupervisor(await response.json()), { headers: { "Cache-Control": "no-store" } });
  } catch { return NextResponse.json({ status: "UNAVAILABLE" }, { status: 503, headers: { "Cache-Control": "no-store" } }); }
}
