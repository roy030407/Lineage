// JS-side mirror of the palette tokens in tokens.css -- three.js materials
// can't read CSS custom properties directly. Keep these two files in sync;
// nothing else in the app should hardcode a hex value outside of them.

export const COLORS = {
  foundry: "#22231f",
  castSteel: "#4a4e47",
  vellum: "#dad5c6",
  beaconGreen: "#4c9a5b",
  beaconAmber: "#e8a33d",
  beaconRed: "#c43b3b",
  steelNeutral: "#7a8380",
} as const;
