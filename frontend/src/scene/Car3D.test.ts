// Regression test for a real bug: cars were once positioned at the same
// height as the station's own box, nesting them fully inside it -- invisible
// and unclickable at every camera angle, for every station in a loaded run.
// CAR_Y must always clear the station's top surface, not just coincide with
// where a station currently happens to be sized.

import { describe, expect, it } from "vitest";

import { CAR_Y } from "./Car3D";
import { BLOCK_SIZE } from "./Station3D";

const CAR_HEIGHT = 0.6; // must match CAR_SIZE[1] in Car3D.tsx

describe("car vertical placement", () => {
  it("renders a car's bottom face strictly above the station block's top surface", () => {
    const stationTopY = BLOCK_SIZE[1]; // block is centered at BLOCK_SIZE[1] / 2
    const carBottomY = CAR_Y - CAR_HEIGHT / 2;
    expect(carBottomY).toBeGreaterThan(stationTopY);
  });
});
