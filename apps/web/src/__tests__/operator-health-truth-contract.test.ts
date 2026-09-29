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
