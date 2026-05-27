type DailyStat = {
  day: string;
  avg_ram_usage_bytes: number;
  request_count: number;
};

type Props = {
  dailyStats: DailyStat[];
  maxDailyRam: number;
  maxDailyRequests: number;
  totalDailyRequests: number;
  refreshDailyStats: () => Promise<void>;
  getErrorMessage: (error: unknown) => string;
  bytesToMb: (bytes: number) => string;
};

export default function DailyTrafficChart({
  dailyStats,
  maxDailyRam,
  maxDailyRequests,
  totalDailyRequests,
  refreshDailyStats,
  getErrorMessage,
  bytesToMb,
}: Props) {
  return (
    <div className="rounded-xl border !border-orange-500 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-100 pb-3">
        <div>
          <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-500">
            5 Day Service Traffic
          </h2>

          <p className="mt-1 text-[11px] text-zinc-400">
            Common API requests counted through the shared route endpoint.
          </p>
        </div>

        <button
          onClick={() =>
            refreshDailyStats().catch((error) =>
              alert(getErrorMessage(error))
            )
          }
          className="h-8 rounded-md border border-zinc-200 bg-white px-3 text-xs font-semibold text-zinc-700 transition hover:bg-zinc-50"
        >
          Refresh Chart
        </button>
      </div>

      {dailyStats.length > 0 ? (
        <div className="mt-4">
          <div className="grid h-48 grid-cols-5 items-end gap-3 border-b border-zinc-200 px-1">
            {dailyStats.map((item) => {
              const ramPercent = Math.max(
                4,
                (item.avg_ram_usage_bytes / maxDailyRam) * 100
              );

              const requestPercent = Math.max(
                4,
                (item.request_count / maxDailyRequests) * 100
              );

              return (
                <div
                  key={item.day}
                  className="flex h-full flex-col justify-end gap-1"
                >
                  <div className="flex h-full items-end gap-1">
                    <div
                      title={`${bytesToMb(item.avg_ram_usage_bytes)} avg RAM`}
                      className="w-full rounded-t !bg-orange-500"
                      style={{ height: `${ramPercent}%` }}
                    />

                    <div
                      title={`${item.request_count} requests`}
                      className="w-full rounded-t !bg-orange-300"
                      style={{ height: `${requestPercent}%` }}
                    />
                  </div>
                </div>
              );
            })}
          </div>

          <div className="mt-2 grid grid-cols-5 gap-3 text-center text-[11px] text-zinc-500">
            {dailyStats.map((item) => (
              <div key={item.day} className="space-y-1">
                <div className="font-semibold text-zinc-700">
                  {new Date(`${item.day}T00:00:00`).toLocaleDateString(
                    undefined,
                    {
                      month: "short",
                      day: "numeric",
                    }
                  )}
                </div>

                <div className="font-mono text-zinc-500">
                  {item.request_count} req
                </div>

                <div className="font-mono text-zinc-500">
                  {bytesToMb(item.avg_ram_usage_bytes)}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-zinc-100 pt-3 text-xs">
            <div className="flex items-center gap-4 text-zinc-500">
              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded !bg-orange-500" />
                Avg memory
              </span>

              <span className="inline-flex items-center gap-1">
                <span className="h-2 w-2 rounded !bg-orange-300" />
                Requests
              </span>
            </div>

            <span className="font-mono text-zinc-700">
              {totalDailyRequests} total requests
            </span>
          </div>
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-dashed border-zinc-200 bg-zinc-50/30 p-4 text-center text-xs text-zinc-400">
          Sync stats to load daily traffic and memory history.
        </p>
      )}
    </div>
  );
}