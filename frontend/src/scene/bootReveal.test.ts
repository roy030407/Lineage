import { beforeEach, describe, expect, it } from "vitest";

import {
  BOOT_CAMERA_S,
  BOOT_RISE_S,
  BOOT_STAGGER_S,
  beginBootReveal,
  bootElapsed,
  cameraApproachFactor,
  resetBootReveal,
  stationRevealFactor,
} from "./bootReveal";

beforeEach(() => resetBootReveal());

describe("bootElapsed", () => {
  it("is null before the reveal begins", () => {
    expect(bootElapsed(10)).toBeNull();
  });

  it("measures from the first begin call and ignores later ones", () => {
    // Every station calls beginBootReveal from its own frame loop, so the
    // call must be idempotent or the last station to mount would restart
    // the sequence for everyone.
    beginBootReveal(10);
    beginBootReveal(50);
    expect(bootElapsed(12)).toBeCloseTo(2);
  });
});

describe("stationRevealFactor", () => {
  it("is 0 when the reveal has not begun", () => {
    expect(stationRevealFactor(null, 0)).toBe(0);
  });

  it("is 0 for a station whose stagger delay has not elapsed", () => {
    expect(stationRevealFactor(BOOT_STAGGER_S * 2, 10)).toBe(0);
  });

  it("reaches exactly 1 once that station's rise window has passed", () => {
    expect(stationRevealFactor(BOOT_STAGGER_S * 3 + BOOT_RISE_S, 3)).toBe(1);
  });

  it("stays strictly between 0 and 1 mid-rise", () => {
    const mid = stationRevealFactor(BOOT_STAGGER_S * 3 + BOOT_RISE_S / 2, 3);
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(1);
  });

  it("reveals earlier stations before later ones", () => {
    // This is what makes the entrance sweep along the line instead of
    // every station popping in at once.
    const elapsed = BOOT_STAGGER_S * 5 + BOOT_RISE_S / 2;
    expect(stationRevealFactor(elapsed, 0)).toBeGreaterThan(stationRevealFactor(elapsed, 5));
  });

  it("clamps to 1 for a far-future elapsed on the last station of a long line", () => {
    expect(stationRevealFactor(9999, 41)).toBe(1);
  });

  it("finishes a 42-station line within a reasonable entrance window", () => {
    // Guards against someone raising BOOT_STAGGER_S until the last station
    // of a real line arrives long after the camera has settled.
    const lastStationDone = BOOT_STAGGER_S * 41 + BOOT_RISE_S;
    expect(lastStationDone).toBeLessThan(3);
    expect(stationRevealFactor(lastStationDone, 41)).toBe(1);
  });
});

describe("cameraApproachFactor", () => {
  it("is 0 before the reveal begins", () => {
    expect(cameraApproachFactor(null)).toBe(0);
  });

  it("is exactly 1 once the flight window has passed", () => {
    expect(cameraApproachFactor(BOOT_CAMERA_S)).toBe(1);
    expect(cameraApproachFactor(9999)).toBe(1);
  });

  it("is monotonic across the flight", () => {
    expect(cameraApproachFactor(0.2)).toBeLessThan(cameraApproachFactor(0.9));
  });

  it("eases out rather than moving linearly", () => {
    // More than half the distance is covered in the first half of the
    // flight: the camera arrives and settles, it does not glide in at a
    // constant rate and stop dead.
    expect(cameraApproachFactor(BOOT_CAMERA_S / 2)).toBeGreaterThan(0.5);
  });
});
