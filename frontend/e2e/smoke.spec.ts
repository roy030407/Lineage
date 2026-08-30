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

// Self-contained per the same serialization rule as hasActiveCar/carMeshState
// above. camera/renderer are exposed on window.__lineageTest specifically so
// this can compute the exact screen-space pixel a moving car occupies --
// see testHooks.ts's comment on why.
function findActiveCarScreenPosition(): { x: number; y: number } | null {
  const hook = window.__lineageTest;
  const scene = hook?.scene;
  const camera = hook?.camera;
  const renderer = hook?.renderer;
  if (!scene || !camera || !renderer) return null;

  let carMesh: unknown = null;
  scene.traverse((obj) => {
    if (obj.userData?.lineageKind === "car" && !carMesh) carMesh = obj;
  });
  const mesh = carMesh as { instanceMatrix?: { array: ArrayLike<number> }; count?: number } | null;
  if (!mesh || !mesh.instanceMatrix || mesh.count === undefined) return null;

  const arr = mesh.instanceMatrix.array;
  for (let i = 0; i < mesh.count; i++) {
    const y = arr[i * 16 + 13];
    if (y <= -500) continue; // HIDDEN_POSITION.y is -1000
    const x = arr[i * 16 + 12];
    const z = arr[i * 16 + 14];
    // camera.position's own constructor gives us a real THREE.Vector3 to
    // call .project() on, without needing THREE exposed as a global.
    const Vector3 = Object.getPrototypeOf(camera.position).constructor as new (
      x: number,
      y: number,
      z: number,
    ) => { project: (c: unknown) => { x: number; y: number } };
    const projected = new Vector3(x, y, z).project(camera);
    const rect = renderer.domElement.getBoundingClientRect();
    return {
      x: rect.left + (projected.x * 0.5 + 0.5) * rect.width,
      y: rect.top + (-projected.y * 0.5 + 0.5) * rect.height,
    };
  }
  return null;
}

test("clicking a car opens its panel (raycast regression guard)", async ({ page }) => {
  // Regression guard for a real, previously-shipped bug: InstancedMesh's
  // raycast() broad-phase-rejects against a boundingSphere cached once, on
  // first raycast, and never recomputed as setMatrixAt moves cars every
  // frame -- Car3D.tsx now calls mesh.computeBoundingSphere() every frame
  // to keep it valid (see that file's comment, and DESIGN.md's diagnosis).
  // That one-line call is exactly the kind of thing a future "optimize the
  // render loop" pass deletes with no type error and every *other* test
  // still green -- the same failure profile as the original occlusion bug.
  // The only test that can catch its removal is one that clicks a car
  // while it's actually moving: global-setup.ts already loads and plays
  // the default run at 60x, and this test deliberately never pauses it. A
  // paused-replay click would still pass with the fix reverted, since a
  // stationary car's stale-at-mount bounding sphere still happens to cover
  // wherever it's stopped.
  await page.goto("/");
  await page
    .waitForFunction(hasActiveCar, undefined, { timeout: 15_000, polling: 250 })
    .catch(() => {});

  // A few retries absorb ordinary timing flakiness (the car keeps moving
  // between computing its screen position and the click landing) without
  // weakening the guard: if the underlying bug were reintroduced, every
  // attempt would miss identically, since the mesh wouldn't be raycastable
  // at all, not just momentarily mispositioned.
  // CarPanel renders its "CAR-XXXXX" heading synchronously the moment a car
  // is selected -- "Stations visited" only appears after the twin-history
  // fetch resolves, which is a real network round trip and not what this
  // test is guarding. Checking the heading confirms the click was received
  // by the car mesh (the actual regression) without depending on that fetch.
  let opened = false;
  for (let attempt = 0; attempt < 5 && !opened; attempt++) {
    const target = await page.evaluate(findActiveCarScreenPosition);
    if (!target) continue;
    await page.mouse.click(target.x, target.y);
    opened = await page
      .getByRole("heading", { level: 2, name: /^CAR-\d+$/ })
      .isVisible({ timeout: 1_000 })
      .catch(() => false);
  }

  expect(opened).toBe(true);
});

test.describe("role views render their own distinctive content", () => {
  test("Operator shows exactly one station's detail, not the whole line", async ({ page }) => {
    await page.goto("/");
    await page.selectOption('select[aria-label="Select role view"]', "operator");
    await expect(page.locator('select[aria-label="My station"]')).toBeVisible();
    // Distinctive, Operator-only content: handover/calibration status and the
    // handover checklist -- neither exists in any other role view, so their
    // presence alone rules out a shared fallback rendering the same thing.
    await expect(page.getByText(/Handover status:/)).toBeVisible();
    await expect(page.getByText("Handover checklist")).toBeVisible();
    // And there must be no 40+ row station table like the other views.
    const rows = await page.locator("table tbody tr").count();
    expect(rows).toBeLessThan(10);
  });

  test("Floor Supervisor shows the full line plus the live alert queue", async ({ page }) => {
    await page.goto("/");
    await page.selectOption('select[aria-label="Select role view"]', "floor_supervisor");
    await expect(page.getByText(/Active alerts \(/)).toBeVisible();
    // The live alert queue itself -- SPC alarms, high-risk cars, bottleneck
    // warnings -- is Floor-Supervisor-only content; its presence (a count
    // label always renders, even at zero) is what rules out a shared
    // fallback rendering the same thing every other view does.
    await expect(page.getByText(/SPC alarms \(/)).toBeVisible();
    await expect(page.getByText(/High-risk cars \(/)).toBeVisible();
    await expect(page.getByText(/Bottleneck warnings \(/)).toBeVisible();
    const rows = await page.locator("table tbody tr").count();
    expect(rows).toBeGreaterThan(30);
  });

  test("Plant Manager shows the weekly report, not a live per-station firehose", async ({
    page,
  }) => {
    await page.goto("/");
    await page.selectOption('select[aria-label="Select role view"]', "plant_manager");
    // Distinctive, Plant-Manager-only content: recurring root causes and the
    // maintenance schedule-vs-predicted table exist in no other role view.
    await expect(page.getByText("Recurring root causes")).toBeVisible();
    await expect(page.getByText("Maintenance: schedule vs. predicted need")).toBeVisible();
    // No live per-station sensor/machine/buffer table -- that's Floor
    // Supervisor's job, not Plant Manager's.
    await expect(page.getByText("Sensor")).toHaveCount(0);
    // The maintenance table alone has one row per station.
    const rows = await page.locator("table tbody tr").count();
    expect(rows).toBeGreaterThan(30);
  });

  test("Leadership shows ROI numbers, never live per-station sensor/machine detail", async ({
    page,
  }) => {
    await page.goto("/");
    await page.selectOption('select[aria-label="Select role view"]', "leadership");
    // Distinctive, Leadership-only content: real cost/value-add totals and
    // the sensor-retrofit ranking -- neither exists in any other role view.
    await expect(page.getByText("Value-added ratio")).toBeVisible();
    await expect(page.getByText(/Sensor retrofit candidates \(/)).toBeVisible();
    // The retrofit table is curated business data (manual stations ranked
    // by economic weight and recurring defects), not a live per-station
    // sensor/machine/buffer table like Floor Supervisor's or the old
    // Plant Manager's -- that distinction, not "zero tables", is the
    // actual invariant here.
    await expect(page.getByText("Sensor", { exact: true })).toHaveCount(0);
  });
});

test("Builder canvas mounts and the spawn tray is present", async ({ page }) => {
  await page.goto("/");
  await page.click('button:has-text("Builder")');
  // The node-graph canvas's spawn tray (Task 8), not the old form-based
  // builder -- this was the long-standing 9th test failing since the
  // harness was built; see NOTES-OVERNIGHT.md.
  await expect(page.getByText(/spawn tray/i)).toBeVisible();
});

test.describe("Builder node-graph canvas (Task 8)", () => {
  interface DraftLine {
    stations: { id: string }[];
  }

  async function currentDraft(page: import("@playwright/test").Page): Promise<DraftLine> {
    return page.evaluate(() => fetch("/api/builder/draft").then((r) => r.json()));
  }

  // Native HTML5 drag-and-drop can't be driven through Playwright's
  // mouse-based drag helpers (there is no real OS-level drag under
  // automation) -- dispatching the actual dragstart/dragover/drop sequence
  // with a real DataTransfer is the standard workaround, and it exercises
  // the app's real onDragStart/onDrop handlers, not a mocked shortcut.
  async function dragTrayTemplateOnto(
    page: import("@playwright/test").Page,
    templateLabel: string,
    point: { x: number; y: number },
  ): Promise<void> {
    await page.evaluate(
      ({ templateLabel, point }) => {
        const tiles = Array.from(document.querySelectorAll('[draggable="true"]'));
        const tile = tiles.find((el) => el.textContent?.trim() === templateLabel);
        if (!tile) throw new Error(`tray tile not found: ${templateLabel}`);
        const dt = new DataTransfer();
        tile.dispatchEvent(new DragEvent("dragstart", { bubbles: true, cancelable: true, dataTransfer: dt }));
        const target = document.elementFromPoint(point.x, point.y);
        if (!target) throw new Error("no element at drop point");
        target.dispatchEvent(
          new DragEvent("dragover", {
            bubbles: true,
            cancelable: true,
            dataTransfer: dt,
            clientX: point.x,
            clientY: point.y,
          }),
        );
        target.dispatchEvent(
          new DragEvent("drop", {
            bubbles: true,
            cancelable: true,
            dataTransfer: dt,
            clientX: point.x,
            clientY: point.y,
          }),
        );
      },
      { templateLabel, point },
    );
  }

  async function nodeRect(
    page: import("@playwright/test").Page,
    stationId: string,
  ): Promise<{ left: number; right: number; top: number; height: number }> {
    const locator = page.locator(`[data-testid="rf__node-${stationId}"]`);
    const box = await locator.boundingBox();
    if (!box) throw new Error(`node not found or not visible: ${stationId}`);
    return { left: box.x, right: box.x + box.width, top: box.y, height: box.height };
  }

  test("tray -> insert mid-line: station count increments and lands between the two targeted stations", async ({
    page,
  }) => {
    await page.goto("/");
    await page.click('button:has-text("Builder")');
    await expect(page.getByText(/spawn tray/i)).toBeVisible();

    const before = await currentDraft(page);
    const upstreamId = before.stations[0].id;
    const downstreamId = before.stations[1].id;

    const a = await nodeRect(page, upstreamId);
    const b = await nodeRect(page, downstreamId);
    // Averages both rects' row centres, not just A's -- upstream/downstream
    // can sit in different zone rows (a zone-transition edge), where the
    // real link is a diagonal, not a horizontal line at A's own height.
    const midpoint = {
      x: (a.right + b.left) / 2,
      y: (a.top + a.height / 2 + b.top + b.height / 2) / 2,
    };

    await dragTrayTemplateOnto(page, "Body", midpoint);
    await expect(page.getByRole("dialog", { name: "Create station" })).toBeVisible();

    const newId = `PW-INSERT-${Date.now()}`;
    await page.fill('input[placeholder="ST-99"]', newId);
    // The "Body" template defaults to instrumented, which requires at least
    // one sensor (validateSensorsMatchAcquisitionMode) -- add the blank one
    // the form offers so the client-side check doesn't block submission.
    await page.click('button:has-text("Add sensor")');
    await page.fill('input[placeholder="sensor id"]', `${newId}-TQ`);
    await page.click('button:has-text("Create station")');
    await expect(page.getByRole("dialog", { name: "Create station" })).not.toBeVisible();

    const after = await currentDraft(page);
    expect(after.stations.length).toBe(before.stations.length + 1);
    const ids = after.stations.map((s) => s.id);
    const upstreamIndex = ids.indexOf(upstreamId);
    expect(ids[upstreamIndex + 1]).toBe(newId);
    expect(ids[upstreamIndex + 2]).toBe(downstreamId);
  });

  test("add a sensorless manual station without it erroring", async ({ page }) => {
    await page.goto("/");
    await page.click('button:has-text("Builder")');
    await expect(page.getByText(/spawn tray/i)).toBeVisible();

    const before = await currentDraft(page);
    const lastId = before.stations[before.stations.length - 1].id;
    const last = await nodeRect(page, lastId);
    const appendPoint = { x: last.right, y: last.top + last.height / 2 };

    await dragTrayTemplateOnto(page, "Manual variant", appendPoint);
    await expect(page.getByRole("dialog", { name: "Create station" })).toBeVisible();

    const newId = `PW-MANUAL-${Date.now()}`;
    await page.fill('input[placeholder="ST-99"]', newId);
    // Deliberately never touches the sensors list -- a manual station with
    // zero sensors is the whole point of this test, not an error state.
    await page.click('button:has-text("Create station")');

    await expect(page.getByRole("dialog", { name: "Create station" })).not.toBeVisible();
    await expect(page.getByText(/failed:/i)).toHaveCount(0);

    const after = await currentDraft(page);
    expect(after.stations.length).toBe(before.stations.length + 1);
    expect(after.stations[after.stations.length - 1].id).toBe(newId);
  });

  test("click a link to cut it", async ({ page }) => {
    await page.goto("/");
    await page.click('button:has-text("Builder")');
    await expect(page.getByText(/spawn tray/i)).toBeVisible();

    const before = await currentDraft(page);
    const upstreamId = before.stations[0].id;
    const downstreamId = before.stations[1].id;

    // Cutting a link now asks for confirmation (it removes the downstream
    // station, not just the conveyor) -- accept the dialog so the cut
    // actually proceeds.
    page.on("dialog", (dialog) => void dialog.accept());
    await page.locator(`[data-testid="rf__edge-${upstreamId}->${downstreamId}"]`).click();

    // The removal round-trips through the dialog and then the backend --
    // poll the draft rather than racing the in-flight DELETE.
    await expect
      .poll(async () => (await currentDraft(page)).stations.length, { timeout: 10_000 })
      .toBe(before.stations.length - 1);

    const after = await currentDraft(page);
    expect(after.stations.length).toBe(before.stations.length - 1);
    expect(after.stations.map((s) => s.id)).not.toContain(downstreamId);
    expect(after.stations.map((s) => s.id)).toContain(upstreamId);
  });
});
