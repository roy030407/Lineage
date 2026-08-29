// Timing for the entrance choreography, deliberately free of React and
// three.js so it is unit-testable with no browser and no canvas.
//
// Read from inside useFrame only. These values change every frame, so
// routing them through React state would re-render the entire scene graph
// sixty times a second in order to move a mesh that three.js could have
// moved directly.

export const BOOT_STAGGER_S = 0.035; // per station: a 42-station line finishes staggering in ~1.4s
export const BOOT_RISE_S = 0.55; // how long a single station takes to rise
export const BOOT_CAMERA_S = 1.8; // the camera flight
export const STATION_RISE_M = 6; // how far below its resting height a station starts

let bootStartedAt: number | null = null;

/** Idempotent: the first call wins. Every station calls this from its own
 * frame loop, so without that guarantee whichever station mounted last
 * would restart the sequence for all of them. */
export function beginBootReveal(elapsedTime: number): void {
  if (bootStartedAt === null) bootStartedAt = elapsedTime;
}

export function bootElapsed(elapsedTime: number): number | null {
  return bootStartedAt === null ? null : elapsedTime - bootStartedAt;
}

/** Test-only, and the reason module state is acceptable here: without it
 * the first test to call beginBootReveal would fix the clock for the whole
 * file. */
export function resetBootReveal(): void {
  bootStartedAt = null;
}

function easeOutCubic(t: number): number {
  return 1 - Math.pow(1 - t, 3);
}

/** 0 = fully hidden, 1 = fully risen. Staggered by sequence index so the
 * reveal sweeps along the line rather than every station appearing at
 * once, which is what makes the length of the line legible on arrival. */
export function stationRevealFactor(elapsed: number | null, sequenceIndex: number): number {
  if (elapsed === null) return 0;
  const local = elapsed - sequenceIndex * BOOT_STAGGER_S;
  if (local <= 0) return 0;
  if (local >= BOOT_RISE_S) return 1;
  return easeOutCubic(local / BOOT_RISE_S);
}

/** 0 = at the wide starting vantage, 1 = at the framed position. */
export function cameraApproachFactor(elapsed: number | null): number {
  if (elapsed === null) return 0;
  if (elapsed >= BOOT_CAMERA_S) return 1;
  return easeOutCubic(elapsed / BOOT_CAMERA_S);
}
