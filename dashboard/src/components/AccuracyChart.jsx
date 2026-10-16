import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

/**
 * Accuracy across federated rounds.
 *
 * Hand-drawn SVG rather than a charting library. The chart has four series and
 * one axis; a library would add half a megabyte to the bundle and then have to
 * be fought to get thin marks, a crosshair tooltip and direct labels.
 *
 * Every series is labelled at its right-hand end as well as in the legend, so
 * identity never rests on colour alone. That is also what lets the aqua series
 * pass review: it sits below 3:1 against the light surface.
 */

const PADDING = { top: 18, right: 92, bottom: 34, left: 46 };
const HEIGHT = 300;

function buildPath(points) {
  return points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x},${point.y}`).join(" ");
}

export default function AccuracyChart({ rounds, series, baseline }) {
  const baselineValue = typeof baseline === "number" ? baseline : null;
  const wrapRef = useRef(null);
  const [hover, setHover] = useState(null);
  const [width, setWidth] = useState(720);


  const geometry = useMemo(() => {
    if (!rounds.length) return null;

    const innerWidth = width - PADDING.left - PADDING.right;
    const innerHeight = HEIGHT - PADDING.top - PADDING.bottom;
    const maxRound = Math.max(...rounds.map((entry) => entry.round));
    const minRound = Math.min(...rounds.map((entry) => entry.round));

    // A fixed 0.4 to 1.0 window. Auto-scaling to the data would make a two point
    // wobble look like a breakthrough, which is exactly the wrong impression
    // when the point of the chart is that federated training converges.
    const yMin = 0.4;
    const yMax = 1.0;

    const xFor = (round) =>
      PADDING.left +
      (maxRound === minRound ? innerWidth / 2 : ((round - minRound) / (maxRound - minRound)) * innerWidth);
    const yFor = (value) =>
      PADDING.top + innerHeight - ((Math.min(Math.max(value, yMin), yMax) - yMin) / (yMax - yMin)) * innerHeight;

    const lines = series
      .map((definition) => {
        const points = rounds
          .map((entry) => {
            const value = definition.accessor(entry);
            return value === null || value === undefined || Number.isNaN(value)
              ? null
              : { x: xFor(entry.round), y: yFor(value), value, round: entry.round };
          })
          .filter(Boolean);
        return { ...definition, points };
      })
      .filter((line) => line.points.length > 0);

    const ticks = [0.4, 0.55, 0.7, 0.85, 1.0];
    const roundTicks = rounds.map((entry) => entry.round);

    // Direct labels are the reason this chart does not depend on colour alone,
    // so they have to stay readable when two series finish at the same accuracy.
    // Lay them out by pushing each one down until it clears the previous label,
    // then shift the whole stack up if it has run past the bottom of the plot.
    const labelCandidates = lines
      .map((line) => ({
        key: line.key,
        label: line.label,
        emphasis: line.emphasis,
        anchor: line.points[line.points.length - 1].y,
      }))
      .concat(
        baselineValue === null || baselineValue === undefined
          ? []
          : [{ key: "__baseline__", label: `centralised ${(baselineValue * 100).toFixed(1)}%`, anchor: yFor(baselineValue), muted: true }],
      )
      .sort((a, b) => a.anchor - b.anchor);

    const MIN_GAP = 14;
    let previous = -Infinity;
    for (const candidate of labelCandidates) {
      candidate.y = Math.max(candidate.anchor, previous + MIN_GAP);
      previous = candidate.y;
    }
    const overflow = previous - (PADDING.top + innerHeight);
    if (overflow > 0) {
      for (const candidate of labelCandidates) candidate.y -= overflow;
    }
    const labelPositions = Object.fromEntries(labelCandidates.map((item) => [item.key, item]));

    return { innerWidth, innerHeight, xFor, yFor, lines, ticks, roundTicks, minRound, maxRound, labelPositions };
  }, [rounds, series, width, baselineValue]);

  const hasGeometry = geometry !== null;

  // Track the container width so the chart reflows with the layout. A
  // ResizeObserver rather than a window resize listener, because the card also
  // changes width when the grid switches to a single column. Below 420px the
  // chart stops shrinking and its own container scrolls instead, so the axis
  // labels never collapse into each other.
  // Measure once synchronously before the browser paints. Waiting for the
  // observer's first callback leaves one frame where the chart is drawn at the
  // fallback width, which shows up as a visible jump on load.
  useLayoutEffect(() => {
    const node = wrapRef.current;
    if (node?.clientWidth) setWidth(Math.max(Math.floor(node.clientWidth), 420));
  }, [hasGeometry]);

  useEffect(() => {
    const node = wrapRef.current;
    if (!node || typeof ResizeObserver === "undefined") return undefined;

    const observer = new ResizeObserver((entries) => {
      const measured = entries[0]?.contentRect?.width;
      if (measured) setWidth(Math.max(Math.floor(measured), 420));
    });
    observer.observe(node);
    return () => observer.disconnect();
    // hasGeometry is in the dependency list because the wrapper element does not
    // exist during the empty state, so the observer has nothing to attach to
    // until the first round arrives.
  }, [hasGeometry]);

  if (!geometry) {
    return <p className="subtitle">No rounds yet. Start a training run and this fills in.</p>;
  }

  const handleMove = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - bounds.left;
    let closest = null;
    for (const entry of rounds) {
      const distance = Math.abs(geometry.xFor(entry.round) - x);
      if (!closest || distance < closest.distance) closest = { entry, distance };
    }
    if (closest && closest.distance < 60) {
      setHover({ round: closest.entry.round, x: geometry.xFor(closest.entry.round) });
    } else {
      setHover(null);
    }
  };

  const hoveredRound = hover ? rounds.find((entry) => entry.round === hover.round) : null;

  return (
    <div className="chart-wrap" ref={wrapRef}>
      <svg
        width={width}
        height={HEIGHT}
        role="img"
        aria-label="Model accuracy by federated round"
        onMouseMove={handleMove}
        onMouseLeave={() => setHover(null)}
        style={{ display: "block" }}
      >
        {/* Recessive gridlines: hairlines behind the data, never competing with it. */}
        {geometry.ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={PADDING.left}
              x2={width - PADDING.right}
              y1={geometry.yFor(tick)}
              y2={geometry.yFor(tick)}
              stroke="var(--gridline)"
              strokeWidth="1"
            />
            <text
              x={PADDING.left - 9}
              y={geometry.yFor(tick) + 4}
              textAnchor="end"
              fontSize="11"
              fill="var(--text-muted)"
            >
              {Math.round(tick * 100)}%
            </text>
          </g>
        ))}

        {/* The centralised baseline: what pooling every hospital's images would
            achieve. The gap between it and the blue line is the cost of privacy. */}
        {baselineValue !== null ? (
          <g>
            <line
              x1={PADDING.left}
              x2={width - PADDING.right}
              y1={geometry.yFor(baselineValue)}
              y2={geometry.yFor(baselineValue)}
              stroke="var(--text-muted)"
              strokeWidth="1"
              strokeDasharray="4 4"
            />
            <text
              x={width - PADDING.right + 7}
              y={(geometry.labelPositions.__baseline__?.y ?? geometry.yFor(baselineValue)) + 4}
              fontSize="11"
              fill="var(--text-muted)"
            >
              {(baselineValue * 100).toFixed(1)}% pooled
            </text>
          </g>
        ) : null}

        <line
          x1={PADDING.left}
          x2={width - PADDING.right}
          y1={HEIGHT - PADDING.bottom}
          y2={HEIGHT - PADDING.bottom}
          stroke="var(--baseline)"
          strokeWidth="1"
        />

        {geometry.roundTicks.map((round) => (
          <text
            key={round}
            x={geometry.xFor(round)}
            y={HEIGHT - PADDING.bottom + 17}
            textAnchor="middle"
            fontSize="11"
            fill="var(--text-muted)"
          >
            {round}
          </text>
        ))}
        <text
          x={PADDING.left + geometry.innerWidth / 2}
          y={HEIGHT - 2}
          textAnchor="middle"
          fontSize="11"
          fill="var(--text-secondary)"
        >
          federated round
        </text>

        {hover ? (
          <line
            x1={hover.x}
            x2={hover.x}
            y1={PADDING.top}
            y2={HEIGHT - PADDING.bottom}
            stroke="var(--baseline)"
            strokeWidth="1"
          />
        ) : null}

        {geometry.lines.map((line) => {
          const last = line.points[line.points.length - 1];
          return (
            <g key={line.key}>
              <path
                d={buildPath(line.points)}
                fill="none"
                stroke={line.color}
                strokeWidth={line.emphasis ? 2.5 : 2}
                strokeLinejoin="round"
                strokeLinecap="round"
                opacity={line.emphasis ? 1 : 0.85}
              />
              {/* A ring in the surface colour keeps overlapping markers legible. */}
              {line.points.map((point) => (
                <circle
                  key={`${line.key}-${point.round}`}
                  cx={point.x}
                  cy={point.y}
                  r={hover && hover.round === point.round ? 5 : 3.5}
                  fill={line.color}
                  stroke="var(--surface-1)"
                  strokeWidth="2"
                />
              ))}
              {(() => {
                const placed = geometry.labelPositions[line.key];
                const labelY = placed ? placed.y : last.y;
                return (
                  <>
                    {Math.abs(labelY - last.y) > 2 ? (
                      <line
                        x1={last.x + 3}
                        y1={last.y}
                        x2={last.x + 9}
                        y2={labelY}
                        stroke={line.color}
                        strokeWidth="1"
                        opacity="0.6"
                      />
                    ) : null}
                    <text
                      x={last.x + 12}
                      y={labelY + 4}
                      fontSize="11"
                      fill="var(--text-secondary)"
                      fontWeight={line.emphasis ? 600 : 400}
                    >
                      {line.label}
                    </text>
                  </>
                );
              })()}
            </g>
          );
        })}
      </svg>

      {hoveredRound ? (
        <div
          className="tooltip"
          style={{
            left: Math.min(Math.max(hover.x - 66, 0), width - 150),
            top: 8,
          }}
        >
          <div className="head">Round {hoveredRound.round}</div>
          {geometry.lines.map((line) => {
            const value = line.accessor(hoveredRound);
            if (value === null || value === undefined || Number.isNaN(value)) return null;
            return (
              <div className="row" key={line.key}>
                <span>
                  <span className="swatch" style={{ background: line.color }} />
                  {line.label}
                </span>
                <span>{(value * 100).toFixed(1)}%</span>
              </div>
            );
          })}
        </div>
      ) : null}

      <div className="legend">
        {geometry.lines.map((line) => (
          <span key={line.key}>
            <span className="swatch" style={{ background: line.color }} />
            {line.legend || line.label}
          </span>
        ))}
        {baselineValue !== null ? (
          <span>
            <span
              className="swatch"
              style={{ background: "transparent", borderTop: "2px dashed var(--text-muted)", borderRadius: 0 }}
            />
            centralised baseline, all data pooled
          </span>
        ) : null}
      </div>
    </div>
  );
}
