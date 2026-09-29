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
