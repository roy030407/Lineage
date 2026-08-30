import { create } from "zustand";

import { getCar, getLine, listRuns, replayControl, simulateRun } from "./api";
import type { CarTwin, LineSpec, LineState, Role, RunSummary } from "./types";

interface LineageStore {
  lineSpec: LineSpec | null;
  lineState: LineState | null;
  previousLineState: LineState | null;
  runs: RunSummary[];

  // Live-stream health, driven by wsClient: whether the socket is currently
  // open, and when the last tick landed (epoch ms) -- lets TopBar tell
  // "live" apart from "stale" apart from "reconnecting".
  wsConnected: boolean;
  lastTickAt: number | null;

  selectedStationId: string | null;
  selectedCarId: string | null;
  selectedCarTwin: CarTwin | null;
  followedCarId: string | null;
  role: Role;
  builderOpen: boolean;
  simulating: boolean;
  simulateError: string | null;
  lastError: string | null;
  lineSpecStatus: "idle" | "loading" | "ready" | "error";
  sceneReady: boolean;

  loadLineSpec: () => Promise<void>;
  retryLoadLineSpec: () => Promise<void>;
  clearError: () => void;
  markSceneReady: () => void;
  loadRuns: () => Promise<void>;
  applyLineState: (state: LineState) => void;
  setWsConnected: (connected: boolean) => void;

  selectStation: (stationId: string | null) => void;
  selectCar: (carId: string | null) => Promise<void>;
  followCar: (carId: string | null) => void;
  setRole: (role: Role) => void;
  setBuilderOpen: (open: boolean) => void;

  loadRun: (runId: string) => Promise<void>;
  simulate: () => Promise<void>;
  play: () => Promise<void>;
  pause: () => Promise<void>;
  step: () => Promise<void>;
  setSpeed: (multiplier: number) => Promise<void>;
}

/** Every action below is invoked as `void fn()` at its call site, so an
 * unhandled rejection is the default failure mode without an explicit
 * catch. Before this, only `simulate` had one: a failed getLine() left
 * lineSpec null forever behind an empty canvas, with no message shown
 * and no way to retry. */
function message(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export const useLineageStore = create<LineageStore>((set, get) => ({
  lineSpec: null,
  lineState: null,
  previousLineState: null,
  runs: [],

  wsConnected: false,
  lastTickAt: null,

  selectedStationId: null,
  selectedCarId: null,
  selectedCarTwin: null,
  followedCarId: null,
  role: "mirror",
  builderOpen: false,
  simulating: false,
  simulateError: null,
  lastError: null,
  lineSpecStatus: "idle",
  sceneReady: false,

  loadLineSpec: async () => {
    set({ lineSpecStatus: "loading", lastError: null });
    try {
      const lineSpec = await getLine();
      set({ lineSpec, lineSpecStatus: "ready" });
    } catch (err) {
      set({ lineSpecStatus: "error", lastError: message(err) });
    }
  },

  retryLoadLineSpec: async () => {
    await get().loadLineSpec();
  },

  clearError: () => set({ lastError: null }),

  /** Set once the 3D scene has actually drawn the line, which is a
   * meaningfully later moment than the LineSpec arriving: mounting 42
   * stations and compiling their shaders took ~2s more in practice,
   * and the boot overlay used to clear at the earlier moment, leaving
   * a black screen in between. Idempotent so the caller can fire it
   * from a frame loop without guarding. */
  markSceneReady: () => {
    if (!get().sceneReady) set({ sceneReady: true });
  },

  loadRuns: async () => {
    try {
      set({ runs: await listRuns() });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },

  applyLineState: (state) => {
    // Only the WS tick path calls this, so it doubles as the staleness clock.
    set((current) => ({
      previousLineState: current.lineState,
      lineState: state,
      lastTickAt: Date.now(),
    }));
  },

  setWsConnected: (connected) => set({ wsConnected: connected }),

  selectStation: (stationId) => set({ selectedStationId: stationId, selectedCarId: null }),

  selectCar: async (carId) => {
    if (carId === null) {
      set({ selectedCarId: null, selectedCarTwin: null });
      return;
    }
    set({ selectedCarId: carId, selectedStationId: null, selectedCarTwin: null });
    const twin = await getCar(carId);
    // Guard against a stale response landing after the user selected something else.
    if (get().selectedCarId === carId) {
      set({ selectedCarTwin: twin });
    }
  },

  followCar: (carId) => set({ followedCarId: carId }),

  setRole: (role) => set({ role }),
  setBuilderOpen: (open) => set({ builderOpen: open }),

  loadRun: async (runId) => {
    try {
      await replayControl({ action: "load", run_id: runId });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
  simulate: async () => {
    set({ simulating: true, simulateError: null });
    try {
      await simulateRun();
      // The backend already loaded it (load_run_into_state); this just
      // starts it playing and refreshes the run-picker list so the freshly
      // generated run shows up there too, not just via this button.
      await replayControl({ action: "play" });
      await get().loadRuns();
    } catch (err) {
      set({ simulateError: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ simulating: false });
    }
  },
  play: async () => {
    try {
      await replayControl({ action: "play" });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
  pause: async () => {
    try {
      await replayControl({ action: "pause" });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
  step: async () => {
    try {
      await replayControl({ action: "step" });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
  setSpeed: async (multiplier) => {
    try {
      await replayControl({ action: "set_speed", speed_multiplier: multiplier });
    } catch (err) {
      set({ lastError: message(err) });
    }
  },
}));
