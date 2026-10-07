import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";
const API_BASE = (process.env.STINKY_API_URL || "http://127.0.0.1:8010").replace(/\/$/, "");

const authority = {
  live_execution: false,
  trading_authority: false,
  rpc_contacted: false,
  transaction_signed: false,
  order_submitted: false,
  wallet_mutated: false,
};

export async function GET() {
  try {
    const response = await fetch(`${API_BASE}/v1/paper/status`, {
      cache: "no-store",
      signal: AbortSignal.timeout(6_000),
    });
    if (!response.ok) throw new Error(`upstream HTTP ${response.status}`);
    const body = await response.json();
    return NextResponse.json(body, { status: 200 });
  } catch (error) {
    return NextResponse.json({
      status: "UNKNOWN",
      paper_only: true,
      live_trading: "LOCKED",
      error: error instanceof Error ? error.message : "paper status unavailable",
      authority,
    }, { status: 200 });
  }
}
