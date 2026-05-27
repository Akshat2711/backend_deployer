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

export function LogPanel({
  title,
  label,
  content,
  accent = false,
}: {
  title: string;
  label: string;
  content: string;
  accent?: boolean;
}) {
  return (
    <div className="flex flex-col gap-2.5">
      {/* Panel Metadata Header */}
      <div className="flex items-center justify-between px-1">
        <h3 className="text-[11px] font-bold uppercase tracking-wider text-zinc-400">
          {title}
        </h3>
        
        <div className="flex items-center gap-1.5">
          {/* Real-time status pulse beacon light */}
          <span className={`h-1.5 w-1.5 rounded-full ${accent ? "bg-cyan-400 animate-pulse" : "bg-zinc-600"}`} />
          <span className="font-mono text-[10px] font-semibold uppercase tracking-wide text-zinc-500">
            {label}
          </span>
        </div>
      </div>

      {/* Terminal Sandbox Viewport */}
      <div
        className={`relative rounded-xl border font-mono transition-all duration-300 ${
          accent
            ? "border-cyan-500/30 bg-cyan-950/20 shadow-[inset_0_1px_1px_rgba(255,255,255,0.05),0_0_20px_rgba(34,211,238,0.05)]"
            : "border-zinc-800 bg-zinc-950/60 shadow-[inset_0_1px_1px_rgba(255,255,255,0.03)]"
        }`}
      >
        {/* Output Canvas Area */}
        <pre
          className={`h-80 min-w-0 overflow-y-auto overflow-x-auto p-4 text-xs font-medium leading-6 whitespace-pre-wrap break-all select-text transition-colors duration-300
            [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden ${
            accent ? "text-cyan-300 selection:bg-cyan-500/30" : "text-zinc-300 selection:bg-zinc-800"
          }`}
        >
          {content}
        </pre>

        {/* Subtle Bottom Ambient Fade Graphic Overlay */}
        <div className="absolute inset-x-0 bottom-0 h-8 pointer-events-none rounded-b-xl bg-gradient-to-t from-zinc-950/40 to-transparent" />
      </div>
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
