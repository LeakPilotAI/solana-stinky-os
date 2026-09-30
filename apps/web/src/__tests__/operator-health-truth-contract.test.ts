import fs from "node:fs";
import path from "node:path";

const root = process.cwd();

test("top bar does not present degraded event log as healthy", () => {
  const source = fs.readFileSync(path.join(root, "src/components/layout/TopBar.tsx"), "utf8");
  expect(source).not.toContain('health?.event_log === "degraded"');
  expect(source).toContain('health?.event_log === "ok"');
});

test("command center preserves unavailable quality-dips evidence", () => {
  const source = fs.readFileSync(path.join(root, "src/components/command-center/CommandCenter.tsx"), "utf8");
  expect(source).toContain('api.bookDips().catch(() => ({ dips: null, available: false }))');
  expect(source).toContain("dipBody.available !== false && dipRows !== null");
  expect(source).toContain("QUALITY DETERIORATION EVIDENCE UNAVAILABLE");
  expect(source).toContain("NO ACTIVE QUALITY DETERIORATION");
});


test("command center renders degraded sections without false zero or empty claims", () => {
  const source = fs.readFileSync(path.join(root, "src/components/command-center/CommandCenter.tsx"), "utf8");
  expect(source).toContain("Command Center degraded. Unavailable sections are not being inferred as zero or empty.");
  expect(source).toContain('c[key] == null ? "—"');
  expect(source).toContain("INVESTIGATION EVIDENCE UNAVAILABLE");
  expect(source).toContain("ALERT EVIDENCE UNAVAILABLE");
  expect(source).toContain("ENTITY EVIDENCE UNAVAILABLE");
  expect(source).toContain('data.trending?.available === false ? "unavailable"');
});


test("command center removes remaining false-live section states", () => {
  const source = fs.readFileSync(path.join(root, "src/components/command-center/CommandCenter.tsx"), "utf8");
  expect(source).toContain("RUNNER EVIDENCE UNAVAILABLE");
  expect(source).toContain("OPPORTUNITY EVIDENCE UNAVAILABLE");
  expect(source).toContain('degraded ? "DEGRADED" : "LIVE"');
  expect(source).toContain("TRENDING EVIDENCE UNAVAILABLE");
  expect(source).toContain('failed.has("alerts") ? "UNAVAILABLE" : "LIVE"');
});


test("command center renders pipeline and precision failures explicitly", () => {
  const source = fs.readFileSync(path.join(root, "src/components/command-center/CommandCenter.tsx"), "utf8");
  expect(source).toContain("PIPELINE EVIDENCE UNAVAILABLE");
  expect(source).toContain("ALERT PRECISION EVIDENCE UNAVAILABLE");
});


test("command center marks cached data stale after refresh failure", () => {
  const source = fs.readFileSync(path.join(root, "src/components/command-center/CommandCenter.tsx"), "utf8");
  expect(source).toContain("Showing last confirmed snapshot — CURRENT LIVENESS UNKNOWN.");
  expect(source).toContain('error ? "Snapshot stale" : "Live poll 6s"');
  expect(source).toContain('error ? "STALE" : degraded ? "DEGRADED" : "LIVE"');
  expect(source).toContain('error ? "STALE" : failed.has("alerts") ? "UNAVAILABLE" : "LIVE"');
  expect(source).not.toContain("Showing last good data — still live.");
});


test("wallets page distinguishes unavailable evidence from measured zero wallets", () => {
  const source = fs.readFileSync(path.join(root, "src/app/wallets/page.tsx"), "utf8");
  expect(source).toContain("SMART WALLET EVIDENCE UNAVAILABLE");
  expect(source).toContain('value={error ? "—" : String(stats.total)}');
  expect(source).toContain("!loading && !error && filtered.length === 0");
});

test("operator auxiliary feeds distinguish fetch failure from legitimate empty history", () => {
  const source = fs.readFileSync(path.join(root, "src/app/operator/page.tsx"), "utf8");
  expect(source).toContain("MOTIF OUTCOME EVIDENCE UNAVAILABLE");
  expect(source).toContain("CORRELATION EVIDENCE UNAVAILABLE");
  expect(source).toContain("DEVELOPER EVIDENCE UNAVAILABLE");
  expect(source).toContain("CALIBRATION EVIDENCE UNAVAILABLE");
  expect(source).toContain("setChangeAvailable(feed !== null)");
  expect(source).toContain("setDeveloperChangeAvailable(developerFeed !== null)");
});


test("paper calibration does not infer unavailable evidence as zero", () => {
  const source = fs.readFileSync(path.join(root, "src/components/command-center/PaperCalibrationPanel.tsx"), "utf8");
  expect(source).toContain('const observed = String(d.status || "").toUpperCase() === "OBSERVED"');
  expect(source).toContain('observed && value != null ? value : "—"');
  expect(source).toContain("PAPER EVIDENCE UNAVAILABLE — counts are not inferred as zero.");
  expect(source).toContain('outcomes unavailable');
  expect(source).toContain('intake unavailable');
});


test("top bar does not infer sentinel or collector health from aggregate api health", () => {
  const source = fs.readFileSync(path.join(root, "src/components/layout/TopBar.tsx"), "utf8");
  expect(source).toContain('<StatusDot ok={null} label="Sentinel" detail="Unknown" />');
  expect(source).toContain('<StatusDot ok={null} label="Collector" detail="Unknown" />');
  expect(source).not.toContain('label="Sentinel" detail={live ? "Live" : "Down"}');
  expect(source).not.toContain('label="Collector" detail={apiOk ? "Live" : "—"}');
});


test("operator surfaces durable supervisor failed or unknown evidence", () => {
  const source = fs.readFileSync(path.join(root, "src/app/operator/page.tsx"), "utf8");
  expect(source).toContain("/api/stinky/v1/system/runtime-supervisors");
  expect(source).toContain("SUPERVISOR FAILURE");
  expect(source).toContain("SUPERVISOR EVIDENCE UNKNOWN");
  expect(source).toContain('runtime?.status === "FAILED"');
  expect(source).toContain('runtime?.status !== "OBSERVED"');
});
