export function FleetMetric({ label, value }: { label: string; value: number }) {
  return (
    <div className="border border-zinc-200 bg-zinc-50 p-3">
      <p className="text-xl font-semibold">{value}</p>
      <p className="text-xs uppercase text-zinc-500">[{label}]</p>
    </div>
  );
}

export function PoolBar({ label, used, max, suffix }: { label: string; used: number; max: number; suffix: string }) {
  const percent = max > 0 ? Math.min((used / max) * 100, 100) : 0;

  return (
    <div>
      <div className="mb-2 flex justify-between text-sm">
        <span>{label}</span>
        <span className="font-semibold">
          {used} / {max}
          {suffix}
        </span>
      </div>
      <div className="terminal-progress" aria-hidden="true">
        {Array.from({ length: 20 }, (_, index) => (
          <span key={index} data-active={index < Math.round(percent / 5)} />
        ))}
      </div>
    </div>
  );
}

export function ActionButton({ label, disabled, onClick }: { label: string; disabled: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="h-9 border border-zinc-300 px-3 text-sm font-semibold uppercase hover:bg-orange-500 disabled:opacity-50"
    >
      [{label}]
    </button>
  );
}

export function DetailMetric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border border-zinc-200 bg-zinc-50 p-3">
      <p className="text-xs font-medium uppercase tracking-wide text-zinc-500">{label}</p>
      <p className="mt-1 text-lg font-semibold">{value}</p>
    </div>
  );
}

export function LogPanel({ title, label, content, accent = false }: { title: string; label: string; content: string; accent?: boolean }) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <h3 className="terminal-title text-sm font-semibold uppercase">{title}</h3>
        <span className="text-xs uppercase text-zinc-500">[{label}]</span>
      </div>
      <pre className={`h-72 min-w-0 overflow-auto  p-4 font-mono text-xs leading-5 ${accent ? "text-cyan-50" : "text-zinc-100"}`}>
        {content}
      </pre>
    </div>
  );
}

export function UsageBar({ label, value, percent, color }: { label: string; value: string; percent: number; color: string }) {
  return (
    <div>
      <div className="mb-2 flex justify-between text-sm">
        <span>{label}</span>
        <span className="font-semibold">{value}</span>
      </div>
      <div className="terminal-progress" aria-hidden="true">
        {Array.from({ length: 20 }, (_, index) => (
          <span key={index} data-active={index < Math.round(Math.min(percent, 100) / 5)} className={color} />
        ))}
      </div>
    </div>
  );
}

export function StatItem({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="bg-zinc-50 p-3">
      <dt className="text-zinc-500">{label}</dt>
      <dd className="mt-1 font-semibold">{value}</dd>
    </div>
  );
}
