import { NextResponse } from "next/server";
import { parseV2Details } from "@/lib/api/intelligence-execution-v2-details";

export const dynamic = "force-dynamic";
const API_BASE = (process.env.STINKY_API_URL || "http://127.0.0.1:8010").replace(/\/$/, "");
export async function GET() {
  try {
    const response = await fetch(`${API_BASE}/v1/intelligence/execution-v2/details`, {
      method: "GET", headers: { Accept: "application/json" }, cache: "no-store", signal: AbortSignal.timeout(6_000),
    });
    if (!response.ok) throw new Error("Unavailable upstream");
    return NextResponse.json(parseV2Details(await response.json()), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ status: "UNAVAILABLE" }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }
}
