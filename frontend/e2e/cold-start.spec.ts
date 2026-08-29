// The regression tier for the four-link cold-start failure.
//
// Every assertion here holds with ZERO replay control calls: no load, no
// play, no set_speed. That constraint is the entire point. The sibling
// smoke suite's globalSetup primes all three before every run, which is
// precisely why it stayed green while the app opened on a blank, frozen,
// unrecoverable screen. If any test here ever starts needing a control
// call to pass, the bug is back.

import { expect, test } from "@playwright/test";

function countByKind(kind: string): number {
  let n = 0;
  window.__lineageTest?.scene?.traverse((obj) => {
    if (obj.userData?.lineageKind === kind) n++;
  });
  return n;
}

// Self-contained: Playwright serializes a function passed to
// waitForFunction/evaluate via .toString() and re-runs only that source in
// the browser, so it cannot call out to anything else in this file.
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

test("stations render on a cold load with no replay control call", async ({ page }) => {
  // Link 3 of the chain: Line3D returned null for any station without a
  // matching StationState, so a null lineState rendered zero stations.
  await page.goto("/");
  await page.waitForFunction(countByKind, "station", { timeout: 15_000 }).catch(() => {});
  expect(await page.evaluate(countByKind, "station")).toBeGreaterThanOrEqual(40);
});

test("a tick arrives unprompted and a car is on the line", async ({ page }) => {
  // Links 1 and 2: nothing autoloaded a run, and the WebSocket replayed an
  // empty snapshot history, so a connected client received zero bytes.
  await page.goto("/");
  await page.waitForFunction(() => (window.__lineageTest?.wsTickCount ?? 0) > 0, {
    timeout: 15_000,
  });
  await page
    .waitForFunction(hasActiveCar, undefined, { timeout: 20_000, polling: 250 })
    .catch(() => {});
  expect(await page.evaluate(hasActiveCar)).toBe(true);
});

test("the transport controls track reality, so pause and resume both work", async ({ page }) => {
  // Link 4. The old TopBar computed isPaused as `undefined === "paused"`,
  // which is false, so on a cold load Play was disabled and Pause was
  // live: the one control that could help was the one greyed out.
  //
  // Asserting a static button combination is not enough, because "Play
  // disabled, Pause enabled" is ALSO the correct state of a genuinely
  // playing line. What actually distinguishes a working control loop from
  // a broken one is whether pressing a control changes anything, so this
  // drives the round trip instead.
  //
  // This is also the regression guard for a second, separate defect found
  // during this work: the backend tick loop used to broadcast nothing at
  // all while paused, so a client's playback_mode stayed "playing"
  // forever and Play never re-enabled. Pausing here would succeed on the
  // server and leave the UI permanently stuck.
  await page.goto("/");
  const play = page.getByRole("button", { name: /^(Play|Replay)$/ });
  const pause = page.getByRole("button", { name: "Pause" });

  await expect(play).toBeVisible();
  await expect(pause).toBeEnabled({ timeout: 15_000 });

  await pause.click();
  await expect(play).toBeEnabled({ timeout: 15_000 });
  await expect(pause).toBeDisabled();

  // Leaves the backend playing again, so this test does not change the
  // state the rest of the suite runs against.
  await play.click();
  await expect(pause).toBeEnabled({ timeout: 15_000 });
});

test("the boot overlay clears once the line spec loads", async ({ page }) => {
  // The overlay must be a transient state, not a permanent curtain: it
  // renders whenever lineSpecStatus is not "ready", so a regression in
  // loadLineSpec's success path would leave it up forever.
  await page.goto("/");
  await expect(page.getByText("Reading line specification")).toHaveCount(0, { timeout: 15_000 });
  await expect(page.getByText("Could not reach the line")).toHaveCount(0);
});
