// The "big number" pattern already used across every role view, extended
// with a small count-up tween on value change -- Phase 5 of the gamified
// rebuild. A plain requestAnimationFrame + lerp hook, no animation library:
// the same technique Station3D/Car3D already use for their own pulse/lerp
// effects elsewhere in this codebase.

import { useEffect, useRef, useState } from "react";

function useCountUp(target: number, durationMs = 500): number {
  const [display, setDisplay] = useState(target);
  const fromRef = useRef(target);
  const rafRef = useRef<number | null>(null);

  useEffect(() => {
    const from = fromRef.current;
    if (from === target) return;

    let startTime: number | null = null;
    function tick(timestamp: number) {
      if (startTime === null) startTime = timestamp;
      const progress = Math.min(1, (timestamp - startTime) / durationMs);
      setDisplay(from + (target - from) * progress);
      if (progress < 1) {
        rafRef.current = requestAnimationFrame(tick);
      } else {
        fromRef.current = target;
      }
    }
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [target, durationMs]);

  return display;
}

interface Props {
  label: string;
  value: number;
  format?: (n: number) => string;
}

export function StatTile({ label, value, format }: Props) {
  const animated = useCountUp(value);
  const displayValue = format ? format(animated) : animated.toFixed(0);

  return (
    <div>
      <p className="eyebrow" style={{ margin: 0 }}>
        {label}
      </p>
      <p className="data" style={{ font: "var(--text-h1)", margin: "var(--space-1) 0 0" }}>
        {displayValue}
      </p>
    </div>
  );
}
