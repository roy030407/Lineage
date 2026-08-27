// Renders a status token (styles/tokens.ts) as colour + shape glyph + label
// text -- never colour alone, so "no data yet" and "faulted" stay
// distinguishable on a projector or for a colour-blind viewer. The label is
// always real text, not just an icon, so the state is never ambiguous.

import type { ShapeToken, StatusToken } from "../styles/tokens";

const SHAPE_GLYPH: Record<ShapeToken, string> = {
  circle: "●", // ●
  triangle: "▲", // ▲
  diamond: "◆", // ◆
  hexagon: "⬡", // ⬡
  ring: "○", // ○
};

interface Props {
  token: StatusToken;
}

export function StatusBadge({ token }: Props) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "var(--space-1)" }}>
      <span aria-hidden="true" style={{ color: token.color }}>
        {SHAPE_GLYPH[token.shape]}
      </span>
      <span>{token.label}</span>
    </span>
  );
}
