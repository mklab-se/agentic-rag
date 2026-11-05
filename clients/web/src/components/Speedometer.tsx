const MIN_ANGLE = -120;
const MAX_ANGLE = 120;
const TICKS = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
const LABELS = [0, 50, 100];
const CENTER = 60;
const RADIUS = 48;

function angleOf(value: number): number {
  return MIN_ANGLE + (value / 100) * (MAX_ANGLE - MIN_ANGLE);
}

function pointOn(radius: number, angle: number): [number, number] {
  const radians = ((angle - 90) * Math.PI) / 180;
  return [CENTER + radius * Math.cos(radians), CENTER + radius * Math.sin(radians)];
}

const [startX, startY] = pointOn(RADIUS, MIN_ANGLE);
const [endX, endY] = pointOn(RADIUS, MAX_ANGLE);
const ARC = `M ${startX} ${startY} A ${RADIUS} ${RADIUS} 0 1 1 ${endX} ${endY}`;

/** A dial from 0 to 100. The model moves it through the set_gauge client tool. */
export function Speedometer({ value }: { value: number }) {
  return (
    <div className="gauge" role="meter" aria-label="Gauge" aria-valuemin={0} aria-valuemax={100} aria-valuenow={value}>
      <svg viewBox="0 0 120 104" aria-hidden="true">
        <path className="gauge-track" d={ARC} pathLength={100} />
        <path className="gauge-fill" d={ARC} pathLength={100} strokeDasharray={`${value} 100`} />
        {TICKS.map((tick) => {
          const [x1, y1] = pointOn(RADIUS - 8, angleOf(tick));
          const [x2, y2] = pointOn(RADIUS - (tick % 50 === 0 ? 14 : 11), angleOf(tick));
          return <line key={tick} className="gauge-tick" x1={x1} y1={y1} x2={x2} y2={y2} />;
        })}
        {LABELS.map((label) => {
          const [x, y] = pointOn(RADIUS - 22, angleOf(label));
          return (
            <text key={label} className="gauge-label" x={x} y={y + 2.5} textAnchor="middle">
              {label}
            </text>
          );
        })}
        <g className="gauge-needle" style={{ transform: `rotate(${angleOf(value)}deg)` }}>
          <line x1={CENTER} y1={CENTER + 6} x2={CENTER} y2={CENTER - RADIUS + 12} />
        </g>
        <circle className="gauge-hub" cx={CENTER} cy={CENTER} r={4} />
        <text className="gauge-value" x={CENTER} y={96} textAnchor="middle">
          {value}
        </text>
      </svg>
    </div>
  );
}
