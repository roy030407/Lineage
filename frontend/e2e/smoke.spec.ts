// Merge-gate smoke suite. Every assertion here checks something real and
// observable -- never "the page returned 200" -- per NOTES-OVERNIGHT.md's
// standing rule for this branch.

import { expect, test } from "@playwright/test";

const STATION_TOP_Y = 1.4; // BLOCK_SIZE[1] in scene/Station3D.tsx -- kept in
// sync by hand, not imported, since this is a browser-side test file with no
// access to the app's own module graph at type-check time.

test("WebSocket connects and at least one tick is received", async ({ page }) => {
  await page.goto("/");
  await page.waitForFunction(() => (window.__lineageTest?.wsTickCount ?? 0) > 0, {
    timeout: 15_000,
  });
  const count = await page.evaluate(() => window.__lineageTest?.wsTickCount ?? 0);
  expect(count).toBeGreaterThan(0);
});

function countByKind(kind: string): number {
  let n = 0;
  window.__lineageTest?.scene?.traverse((obj) => {
    if (obj.userData?.lineageKind === kind) n++;
  });
  return n;
}

test("at least 40 station meshes exist in the scene", async ({ page }) => {
  await page.goto("/");
  // Waiting for the Canvas to mount (scene != null) isn't enough -- lineSpec
  // and lineState both still have to load asynchronously before Station3D
  // components actually exist in the scene graph. Poll the real count
  // directly instead of a fixed guess at how long that takes.
  await page.waitForFunction(countByKind, "station", { timeout: 15_000 }).catch(() => {});
  const count = await page.evaluate(countByKind, "station");
  expect(count).toBeGreaterThanOrEqual(40);
});

// Self-contained (no reference to other Node-side functions): Playwright
// serializes a function passed to waitForFunction/evaluate via .toString()
// and re-runs *only that source* in the browser, so it can't call out to
// carMeshState() below even though both are defined in this same file.
function hasActiveCar(): boolean {
  let carMesh: unknown = null;
  window.__lineageTest?.scene?.traverse((obj) => {
    if (obj.userData?.lineageKind === "car") carMesh = obj;
  });
  const mesh = carMesh as { instanceMatrix?: { array: ArrayLike<number> }; count?: number } | null;
  if (!mesh || !mesh.instanceMatrix || mesh.count === undefined) return false;
  const arr = mesh.instanceMatrix.array;
  for (let i = 0; i < mesh.count; i++) {
    if (arr[i * 16 + 13] > -500) return true; // HIDDEN_POSITION.y is -1000
  }
  return false;
}

function carMeshState(): { found: boolean; anyActive: boolean; maxY: number | null } {
  // Loosely typed here on purpose: this runs inside the browser's own JS
  // context via page.evaluate/waitForFunction, a boundary where precise TS
  // typing of a three.js InstancedMesh buys nothing.
  let carMesh: unknown = null;
  window.__lineageTest?.scene?.traverse((obj) => {
    if (obj.userData?.lineageKind === "car") carMesh = obj;
  });
  const mesh = carMesh as { instanceMatrix?: { array: ArrayLike<number> }; count?: number } | null;
  if (!mesh || !mesh.instanceMatrix || mesh.count === undefined) {
    return { found: false, anyActive: false, maxY: null };
  }
  const arr = mesh.instanceMatrix.array;
  let anyActive = false;
  let maxY = -Infinity;
  for (let i = 0; i < mesh.count; i++) {
    const y = arr[i * 16 + 13]; // translation.y is element 13 of a column-major mat4
    if (y > -500) {
      // HIDDEN_POSITION.y is -1000 in Car3D.tsx; anything well above that is a real car
      anyActive = true;
      if (y > maxY) maxY = y;
    }
  }
  return { found: true, anyActive, maxY };
}

test("at least one car mesh exists, positioned strictly above the station block top", async ({
  page,
}) => {
  await page.goto("/");
  // Poll the real, rendered state directly rather than guessing how long
  // lineSpec + a few WS ticks take to arrive and be applied. The predicate
  // must return a plain boolean -- carMeshState()'s result object is always
  // truthy, which would make waitForFunction resolve on the first poll.
  await page
    .waitForFunction(hasActiveCar, undefined, { timeout: 15_000, polling: 250 })
    .catch(() => {});
  const result = await page.evaluate(carMeshState);

  expect(result.found).toBe(true);
  expect(result.anyActive).toBe(true);
  expect(result.maxY).toBeGreaterThan(STATION_TOP_Y);
});

test.describe("role views render their own distinctive content", () => {
  test("Operator shows exactly one station, not the whole line", async ({ page }) => {
    await page.goto("/");
    await page.selectOption('select[aria-label="Select role view"]', "operator");
    await expect(page.locator('select[aria-label="My station"]')).toBeVisible();
    // A per-station form (sensor health, live readings) should be present,
    // and there should be no 40+ row station table like the other views.
    const rows = await page.locator("table tbody tr").count();
    expect(rows).toBeLessThan(10);
  });

  test("Floor Supervisor shows the full line plus an alert count", async ({ page }) => {
    await page.goto("/");
    await page.selectOption('select[aria-label="Select role view"]', "floor_supervisor");
    await expect(page.getByText(/Active alerts \(/)).toBeVisible();
    const rows = await page.locator("table tbody tr").count();
    expect(rows).toBeGreaterThan(30);
  });

  test("Plant Manager shows summary counters plus the full station table", async ({ page }) => {
    await page.goto("/");
    await page.selectOption('select[aria-label="Select role view"]', "plant_manager");
    await expect(page.getByText("Occupied stations")).toBeVisible();
    const rows = await page.locator("table tbody tr").count();
    expect(rows).toBeGreaterThan(30);
  });

  test("Leadership shows summary counters ONLY -- no per-station table at all", async ({
    page,
  }) => {
    await page.goto("/");
    await page.selectOption('select[aria-label="Select role view"]', "leadership");
    await expect(page.getByText("Occupied stations")).toBeVisible();
    await expect(page.locator("table")).toHaveCount(0);
  });
});

test("Builder canvas mounts and the spawn tray is present", async ({ page }) => {
  await page.goto("/");
  await page.click('button:has-text("Builder")');
  // Deliberately checks for the node-graph canvas's spawn tray specifically
  // (Task 8), not today's form-based builder -- expected to fail until that
  // lands; see NOTES-OVERNIGHT.md.
  await expect(page.getByText(/spawn tray/i)).toBeVisible();
});
