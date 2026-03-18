import assert from "node:assert/strict";
import test from "node:test";
import type { FaceTrackState } from "../../types";
import { computeOverlayBBoxPercent } from "../DeviceMonitor";

const sampleState = (overrides: Partial<FaceTrackState> = {}): FaceTrackState => ({
  found: true,
  bbox: [32, 24, 64, 48],
  frame_w: 320,
  frame_h: 240,
  ex: 0.1,
  ex_smooth: 0.08,
  turn: 0.05,
  lost: 0,
  sent: true,
  mode: "normal",
  scene: "desk",
  ts_ms: Date.now(),
  ...overrides,
});

test("maps bbox pixels to overlay percentages", () => {
  const out = computeOverlayBBoxPercent(sampleState(), true, false);
  assert.ok(out);
  assert.equal(out.left, 10);
  assert.equal(out.top, 10);
  assert.equal(out.width, 20);
  assert.equal(out.height, 20);
});

test("returns null for stale data", () => {
  const out = computeOverlayBBoxPercent(sampleState(), true, true);
  assert.equal(out, null);
});

test("returns null when overlay disabled", () => {
  const out = computeOverlayBBoxPercent(sampleState(), false, false);
  assert.equal(out, null);
});
