import { create } from "zustand";

import { getCar, getLine, listRuns, replayControl } from "./api";
import type { CarTwin, LineSpec, LineState, Role, RunSummary } from "./types";

interface LineageStore {
  lineSpec: LineSpec | null;
  lineState: LineState | null;
  previousLineState: LineState | null;
  runs: RunSummary[];

  selectedStationId: string | null;
  selectedCarId: string | null;
  selectedCarTwin: CarTwin | null;
  followedCarId: string | null;
  role: Role;
  builderOpen: boolean;

  loadLineSpec: () => Promise<void>;
  loadRuns: () => Promise<void>;
  applyLineState: (state: LineState) => void;

  selectStation: (stationId: string | null) => void;
  selectCar: (carId: string | null) => Promise<void>;
  followCar: (carId: string | null) => void;
  setRole: (role: Role) => void;
  setBuilderOpen: (open: boolean) => void;

  loadRun: (runId: string) => Promise<void>;
  play: () => Promise<void>;
  pause: () => Promise<void>;
  step: () => Promise<void>;
  setSpeed: (multiplier: number) => Promise<void>;
}

export const useLineageStore = create<LineageStore>((set, get) => ({
  lineSpec: null,
  lineState: null,
  previousLineState: null,
  runs: [],

  selectedStationId: null,
  selectedCarId: null,
  selectedCarTwin: null,
  followedCarId: null,
  role: "mirror",
  builderOpen: false,

  loadLineSpec: async () => {
    const lineSpec = await getLine();
    set({ lineSpec });
  },

  loadRuns: async () => {
    const runs = await listRuns();
    set({ runs });
  },

  applyLineState: (state) => {
    set((current) => ({ previousLineState: current.lineState, lineState: state }));
  },

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
    await replayControl({ action: "load", run_id: runId });
  },
  play: async () => {
    await replayControl({ action: "play" });
  },
  pause: async () => {
    await replayControl({ action: "pause" });
  },
  step: async () => {
    await replayControl({ action: "step" });
  },
  setSpeed: async (multiplier) => {
    await replayControl({ action: "set_speed", speed_multiplier: multiplier });
  },
}));
