// Visual meter for a prediction's confidence value: a small labeled
// horizontal bar plus the percentage. A null/undefined value is the
// backend's honest "unknown" (an abstention, or a probability it refused
// to fabricate) -- rendered as an explicit hatched "n/a", never as 0%,
// so an abstaining model can't be misread as a supremely confident one.

interface Props {
  label: string;
  /** Fraction in [0, 1], or null/undefined when the backend abstained. */
  value: number | null | undefined;
}

const BAR_WIDTH = "6rem";
const BAR_HEIGHT = "0.5rem";

export function ConfidenceMeter({ label, value }: Props) {
  const known = value !== null && value !== undefined;
  const pct = known ? Math.min(1, Math.max(0, value)) * 100 : 0;

  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: "var(--space-2)",
        marginRight: "var(--space-4)",
      }}
    >
      <span className="eyebrow">{label}</span>
      <span
        className={known ? undefined : "hazard-hatch"}
        role="meter"
        aria-label={label}
        aria-valuenow={known ? Math.round(pct) : undefined}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuetext={known ? `${Math.round(pct)}%` : "not available"}
        style={{
          display: "inline-block",
          width: BAR_WIDTH,
          height: BAR_HEIGHT,
          background: known ? "var(--color-foundry)" : undefined,
          border: "var(--border-width-hairline) solid var(--color-steel-neutral)",
          borderRadius: "var(--radius-sm)",
          overflow: "hidden",
        }}
      >
        {known && (
          <span
            style={{
              display: "block",
              width: `${pct}%`,
              height: "100%",
              background: "var(--color-hud-accent)",
            }}
          />
        )}
      </span>
      <span className="data" style={known ? undefined : { color: "var(--color-steel-neutral)" }}>
        {known ? `${Math.round(pct)}%` : "n/a"}
      </span>
    </span>
  );
}
