// Single source of truth for the design system: palette, type scale,
// spacing, and the status vocabulary shared by the Mirror (3D), every 2D
// role view, and the Builder. Nothing downstream should redefine a colour,
// font, spacing value, or status-state colour/shape/label of its own --
// import it from here.
//
// tokens.css's :root block used to hardcode these same values a second
// time (three.js materials can't read CSS custom properties, so a JS-side
// copy was unavoidable) -- the two were only kept in sync by a comment
// asking nicely. applyDesignTokens() below replaces that: it injects the
// CSS custom properties from the values here at startup (called once from
// main.tsx), so there is exactly one place any of these numbers live.

import type { MachineHealth, RiskLevel, SensorHealth, SPCState, Zone } from "../state/types";

export const PALETTE = {
  foundry: "#22231f", // base canvas
  castSteel: "#4a4e47", // panels, dividers, structural chrome
  vellum: "#dad5c6", // primary text
  beaconGreen: "#4c9a5b",
  beaconAmber: "#e8a33d",
  beaconRed: "#c43b3b",
  steelNeutral: "#7a8380", // no signal / not applicable -- shape carries the meaning, not a new hue
  zoneBody: "#5b7a9a", // muted steel-blue -- Builder node header stripes only, never a status colour
  zonePaint: "#8a6a9e", // muted plume/violet
  zoneFinal: "#a98249", // muted bronze
  hudAccent: "#5ec9d6", // HUD panel border/focus accent -- a cyan deliberately outside every
  // status colour (green/amber/red/steelNeutral) and zone colour above, so it always reads as
  // "this is UI chrome", never as a health or zone signal of its own.
  hudPanelDeep: "#171813", // darker-than-foundry panel backing, for the HUD "floating card" look
} as const;

export const FONT_FAMILIES = {
  display: `"Big Shoulders Condensed", "Arial Narrow", sans-serif`,
  body: `"IBM Plex Sans", system-ui, sans-serif`,
  mono: `"IBM Plex Mono", "Consolas", monospace`,
} as const;

export const TYPE_SCALE = {
  display: `700 2.5rem/1.1 ${FONT_FAMILIES.display}`,
  h1: `600 1.5rem/1.2 ${FONT_FAMILIES.display}`,
  h2: `500 1.125rem/1.3 ${FONT_FAMILIES.display}`,
  body: `400 0.9375rem/1.5 ${FONT_FAMILIES.body}`,
  eyebrow: `600 0.75rem/1.4 ${FONT_FAMILIES.body}`,
  data: `400 0.875rem/1.4 ${FONT_FAMILIES.mono}`,
  dataHero: `500 1.75rem/1.2 ${FONT_FAMILIES.mono}`,
} as const;

export const EYEBROW_LETTER_SPACING = "0.04em";

// One step = 0.25rem (4px). Every margin/padding/gap in the app should
// read one of these via var(--space-N), never a literal rem/px value.
export const SPACING = {
  1: "0.25rem",
  2: "0.5rem",
  3: "0.75rem",
  4: "1rem",
  6: "1.5rem",
  8: "2rem",
  12: "3rem",
} as const;

// Recurring container widths -- not a spacing step, but still a value that
// shouldn't be hand-typed per component.
export const WIDTHS = {
  sidePanel: "320px",
  builderColumn: "360px",
  readableMeasure: "480px",
} as const;

// HUD-panel chrome (Phase 5 of the gamified rebuild): a single dial each for
// "how chunky do corners read" and "how thick does a border read" -- bump
// these once here, every panel/tile built on them reads rounder/bolder
// immediately, rather than each component guessing its own border-radius.
export const RADIUS = {
  sm: "4px",
  md: "8px",
  chunky: "14px",
} as const;

export const BORDER_WIDTH = {
  hairline: "1px",
  chunky: "2px",
} as const;

// A single value, not a record -- HudPanel's "floating card over the
// industrial background" look needs exactly one drop shadow, not a scale.
export const PANEL_SHADOW = "0 8px 24px rgba(0, 0, 0, 0.5)";

export type ShapeToken = "circle" | "triangle" | "diamond" | "hexagon" | "ring";

export interface StatusToken {
  color: string;
  shape: ShapeToken;
  label: string;
}

// One shape vocabulary, reused by every status domain below, so "shape"
// carries a single consistent meaning everywhere -- never colour alone,
// so the distinction survives a projector or colour-blind viewer:
//   circle   = healthy / in control / low risk
//   triangle = caution, needs attention
//   diamond  = fault
//   hexagon  = pending -- not a fault, just no data yet
//   ring     = not applicable / unknown -- no meaningful signal at all

export const SENSOR_HEALTH_TOKENS: Record<SensorHealth, StatusToken> = {
  green: { color: PALETTE.beaconGreen, shape: "circle", label: "Reporting" },
  red: { color: PALETTE.beaconRed, shape: "diamond", label: "Sensor Fault" },
  not_yet_reporting: { color: PALETTE.steelNeutral, shape: "hexagon", label: "No Data Yet" },
  not_applicable: { color: PALETTE.steelNeutral, shape: "ring", label: "No Sensor" },
};

export const MACHINE_HEALTH_TOKENS: Record<MachineHealth, StatusToken> = {
  green: { color: PALETTE.beaconGreen, shape: "circle", label: "Maintained" },
  red: { color: PALETTE.beaconRed, shape: "diamond", label: "Maintenance Overdue" },
};

export const SPC_STATE_TOKENS: Record<SPCState, StatusToken> = {
  in_control: { color: PALETTE.beaconGreen, shape: "circle", label: "In Control" },
  out_of_control: { color: PALETTE.beaconRed, shape: "diamond", label: "Out of Control" },
  unknown: { color: PALETTE.steelNeutral, shape: "ring", label: "Unknown" },
  environment_invalid: {
    color: PALETTE.beaconAmber,
    shape: "triangle",
    label: "Environment Invalid",
  },
};

export const RISK_LEVEL_TOKENS: Record<RiskLevel, StatusToken> = {
  low: { color: PALETTE.beaconGreen, shape: "circle", label: "Low Risk" },
  medium: { color: PALETTE.beaconAmber, shape: "triangle", label: "Medium Risk" },
  high: { color: PALETTE.beaconRed, shape: "diamond", label: "High Risk" },
  unknown_risk: { color: PALETTE.steelNeutral, shape: "ring", label: "Unknown Risk" },
};

// Zone identity, not status -- the Mirror separates zones by real geometry
// (each its own conveyor row); the Builder's flat 2D canvas has no
// equivalent row separation to lean on, so each zone gets its own header
// stripe colour instead. Deliberately outside the shape vocabulary above:
// this is "which zone", never "how healthy".
export const ZONE_TOKENS: Record<Zone, { color: string; label: string }> = {
  body: { color: PALETTE.zoneBody, label: "Body" },
  paint: { color: PALETTE.zonePaint, label: "Paint" },
  final: { color: PALETTE.zoneFinal, label: "Final" },
};

function kebabCase(camel: string): string {
  return camel.replace(/([A-Z])/g, "-$1").toLowerCase();
}

/** Injects every palette/type/spacing/width value above as a CSS custom
 * property on :root. Call once, before the app renders (see main.tsx) --
 * plain CSS (tokens.css's .eyebrow/.data/etc rules) and every component's
 * var(--color-*)/var(--text-*)/var(--space-*) read are sourced from here,
 * not from a second hardcoded :root block. */
export function applyDesignTokens(): void {
  const root = document.documentElement.style;
  for (const [name, value] of Object.entries(PALETTE)) {
    root.setProperty(`--color-${kebabCase(name)}`, value);
  }
  for (const [name, value] of Object.entries(TYPE_SCALE)) {
    root.setProperty(`--text-${kebabCase(name)}`, value);
  }
  for (const [name, value] of Object.entries(FONT_FAMILIES)) {
    root.setProperty(`--font-${kebabCase(name)}`, value);
  }
  for (const [name, value] of Object.entries(SPACING)) {
    root.setProperty(`--space-${name}`, value);
  }
  for (const [name, value] of Object.entries(WIDTHS)) {
    root.setProperty(`--width-${kebabCase(name)}`, value);
  }
  for (const [name, value] of Object.entries(RADIUS)) {
    root.setProperty(`--radius-${name}`, value);
  }
  for (const [name, value] of Object.entries(BORDER_WIDTH)) {
    root.setProperty(`--border-width-${kebabCase(name)}`, value);
  }
  root.setProperty("--shadow-panel", PANEL_SHADOW);
  root.setProperty("--letter-spacing-eyebrow", EYEBROW_LETTER_SPACING);
}
