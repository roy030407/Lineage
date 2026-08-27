// A chunky-bordered "floating card" wrapper for grouping a role view's
// sections -- Phase 5 of the gamified rebuild. Purely chrome: it never
// touches what's inside it, so wrapping an existing section (its own
// eyebrow heading, table, whatever) is mechanical, not a data-logic
// rewrite. accentColor defaults to the shared HUD accent; pass a zone
// colour instead when a panel is scoped to one zone, same as the Builder's
// own zone stripes -- never a status colour, that vocabulary means
// something else entirely (see styles/tokens.ts).

import type { ReactNode } from "react";

interface Props {
  accentColor?: string;
  children: ReactNode;
}

export function HudPanel({ accentColor, children }: Props) {
  return (
    <div
      style={{
        background: "var(--color-hud-panel-deep)",
        border: `var(--border-width-chunky) solid ${accentColor ?? "var(--color-hud-accent)"}`,
        borderRadius: "var(--radius-chunky)",
        boxShadow: "var(--shadow-panel)",
        padding: "var(--space-4)",
        marginTop: "var(--space-4)",
      }}
    >
      {children}
    </div>
  );
}
