import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
const API_BASE = (process.env.STINKY_API_URL || "http://127.0.0.1:8010").replace(/\/$/, "");

export async function POST(request: Request) {
  try {
    const response = await fetch(`${API_BASE}/v1/paper/evaluation-artifact/verify`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(await request.json()), cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    if (!response.ok) throw new Error("Artifact verification unavailable");
    return NextResponse.json(await response.json(), { headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({
      status: "UNKNOWN", valid: false, reason: "artifact_verification_unavailable",
      paper_only: true, live_execution: false, trading_authority: false, automatic_activation: false,
    }, { headers: { "Cache-Control": "no-store" } });
  }
}
