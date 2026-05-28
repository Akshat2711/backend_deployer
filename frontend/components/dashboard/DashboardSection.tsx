"use client";

import { useMemo, useState } from "react";
import { githubWebhookUrl, loadBalancedDeploymentUrl } from "@/lib/api";
import { getErrorMessage } from "@/lib/errors";
import { bytesToMb, formatRuntime, statusClass } from "@/lib/format";
import type { DailyDeploymentStats, Deployment, DeploymentAction, FileEntry, InstanceStats, Stats } from "@/lib/types";
import { ActionButton, DetailMetric, LogPanel, StatItem, UsageBar } from "./ui";
import DailyTrafficChart from "@/components/dashboard/DailyTrafficChart";

type Props = {
  message: string;
  setMessage: (s: string) => void;
  deployments: Deployment[];
  selectedDeployment: Deployment | null;
  selectDeployment: (id: number) => void;
  refreshDeployments: () => Promise<void>;
  runAction: (id: number, action: DeploymentAction) => Promise<void>;
  redeployGithub: (id: number) => Promise<void>;
  actionId: number | null;
  refreshStats: () => Promise<void>;
  fetchLogs: () => Promise<void>;
  logTarget: string;
  setLogTarget: (s: string) => void;
  toggleStream: () => void;
  isStreaming: boolean;
  logs: string;
  liveLogs: string[];
  runShellCommand: () => Promise<void>;
  shellCommand: string;
  setShellCommand: (s: string) => void;
  shellOutput: string;
  toolBusy: boolean;
  browseFiles: (path?: string) => Promise<void>;
  filePath: string;
  setFilePath: (p: string) => void;
  fileEntries: FileEntry[];
  openFile: (path: string) => Promise<void>;
  editorPath: string;
  setEditorPath: (p: string) => void;
  saveFile: () => Promise<void>;
  editorContent: string;
  setEditorContent: (c: string) => void;
  uploadPath: string;
  setUploadPath: (p: string) => void;
  setContainerUpload: (f: File | null) => void;
  containerUpload: File | null;
  uploadFileToContainer: () => Promise<void>;
  stats: Stats | null;
  instanceStats: InstanceStats[];
  dailyStats: DailyDeploymentStats[];
  refreshDailyStats: () => Promise<void>;
};

type TelemetryView = "all" | string;

export default function DashboardSection(props: Props) {
  const {
    message,
    deployments,
    selectedDeployment,
    selectDeployment,
    runAction,
    redeployGithub,
    actionId,
    refreshStats,
    fetchLogs,
    logTarget,
    setLogTarget,
    toggleStream,
    isStreaming,
    logs,
    liveLogs,
    runShellCommand,
    shellCommand,
    setShellCommand,
    shellOutput,
    toolBusy,
    browseFiles,
    filePath,
    setFilePath,
    fileEntries,
    openFile,
    editorPath,
    setEditorPath,
    saveFile,
    editorContent,
    setEditorContent,
    uploadPath,
    setUploadPath,
    setContainerUpload,
    containerUpload,
    uploadFileToContainer,
    stats,
    instanceStats,
    dailyStats,
    refreshDailyStats,
  } = props;
  const [telemetryView, setTelemetryView] = useState<TelemetryView>("all");
  const selectedPorts = selectedDeployment?.assigned_ports?.length
    ? selectedDeployment.assigned_ports
    : selectedDeployment
      ? [selectedDeployment.assigned_port]
      : [];
  const selectedPortLinks = instanceStats.length
    ? instanceStats.filter((item) => item.running).map((item) => ({ port: item.assigned_port, label: `Instance ${item.instance_index}` }))
    : selectedPorts.map((port, index) => ({ port, label: `Instance ${index + 1}` }));
  const effectiveTelemetryView = telemetryView === "all" || instanceStats.some((item) => String(item.instance_index) === telemetryView)
    ? telemetryView
    : "all";
  const telemetryStats = useMemo(() => {
    if (instanceStats.length === 0) return stats;
    if (effectiveTelemetryView !== "all") {
      return instanceStats.find((item) => String(item.instance_index) === effectiveTelemetryView) ?? instanceStats[0];
    }

    const runningCount = instanceStats.filter((item) => item.running).length;
    const maxUptime = Math.max(...instanceStats.map((item) => item.uptime_seconds), 0);
    const restartTotal = instanceStats.reduce((sum, item) => sum + item.restart_count, 0);
    const ramUsage = instanceStats.reduce((sum, item) => sum + item.ram_usage_bytes, 0);
    const ramLimit = instanceStats.reduce((sum, item) => sum + item.ram_limit_bytes, 0);
    const cpuAverage = instanceStats.reduce((sum, item) => sum + item.cpu_usage_percent, 0) / instanceStats.length;

    return {
      deployment_id: instanceStats[0].deployment_id,
      cpu_usage_percent: cpuAverage,
      ram_usage_bytes: ramUsage,
      ram_limit_bytes: ramLimit,
      uptime_seconds: maxUptime,
      restart_count: restartTotal,
      running: runningCount > 0,
      collected_at: null,
    };
  }, [effectiveTelemetryView, instanceStats, stats]);
  const selectedInstanceStats = effectiveTelemetryView === "all"
    ? null
    : instanceStats.find((item) => String(item.instance_index) === effectiveTelemetryView) ?? null;
  const maxDailyRam = Math.max(...dailyStats.map((item) => item.avg_ram_usage_bytes), 1);
  const maxDailyRequests = Math.max(...dailyStats.map((item) => item.request_count), 1);
  const totalDailyRequests = dailyStats.reduce((sum, item) => sum + item.request_count, 0);

  const [viewMode, setViewMode] = useState<"fetch" | "live">("fetch");

  return (
    <section className="space-y-6">
      {message ? (
        <div className="rounded-lg border border-cyan-100  px-4 py-3 font-mono text-xs text-cyan-800 shadow-sm">
          {message}
        </div>
      ) : null}

      {/* Cluster Table Matrix View Container */}
      <div className="rounded-xl border !border-orange-500 bg-white shadow-sm overflow-hidden">
        <div className="border-b border-zinc-100 p-5">
          <h2 className="text-sm font-bold uppercase tracking-wider text-zinc-700">Cluster Infrastructure Deployments</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[780px] text-left text-xs">
            <thead className="bg-zinc-50 font-bold uppercase tracking-wider text-zinc-500 border-b border-zinc-100">
              <tr>
                <th className="px-5 py-3.5">ID</th>
                <th className="px-5 py-3.5">Target Image</th>
                <th className="px-5 py-3.5">Node Status</th>
                <th className="px-5 py-3.5">Routing Ports</th>
                <th className="px-5 py-3.5">Resource Caps</th>
                <th className="px-5 py-3.5">Last Mutation Block</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {deployments.map((deployment) => (
                <tr
                  key={deployment.id}
                  onClick={() => selectDeployment(deployment.id)}
                  className={`cursor-pointer transition hover:bg-zinc-50/80 ${selectedDeployment?.id === deployment.id ? "!bg-orange-500" : ""}`}
                >
                  <td className="px-5 py-4 font-bold text-zinc-900">#{deployment.id}</td>
                  <td className="px-5 py-4 font-mono text-zinc-600">{deployment.image_name}</td>
                  <td className="px-5 py-4">
                    <span className={`inline-flex rounded-md border px-2 py-0.5 text-[10px] font-bold uppercase tracking-tight ${statusClass(deployment.status)}`}>
                      {deployment.status}
                    </span>
                  </td>
                  <td className="px-5 py-4 font-mono text-zinc-600">
                    {(deployment.assigned_ports?.length ? deployment.assigned_ports : [deployment.assigned_port]).join(", ")}:{deployment.internal_port}
                  </td>
                  <td className="px-5 py-4 text-zinc-600">
                    {deployment.cpu_limit} CPU / {deployment.ram_limit} MB / {deployment.storage_limit_mb} MB disk
                  </td>
                  <td className="px-5 py-4 text-zinc-400 font-mono">{new Date(deployment.updated_at).toLocaleString()}</td>
                </tr>
              ))}
              {deployments.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-5 py-12 text-center font-medium text-zinc-400 bg-zinc-50/30">
                    No runtime clusters operating. Trigger top actions to initialize context routing.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {selectedDeployment ? (
        <div className="space-y-6">
          
          {/* Section: Operational Control Plane & Real-Time Statistics */}
          <div className="grid gap-6 lg:grid-cols-3">
            {/* Core Pod Node Actions Box */}
            <div className="lg:col-span-2 rounded-xl border !border-orange-500 bg-white p-5 shadow-sm space-y-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div>
                  <h2 className="text-base font-bold text-zinc-900">Pod Node Identity #{selectedDeployment.id}</h2>
                  <p className="mt-1 break-all font-mono text-xs text-zinc-400">
                    {(selectedDeployment.container_ids?.length ? selectedDeployment.container_ids : [selectedDeployment.container_id]).filter(Boolean).join(" / ") || "No virtual hash identifier generated"}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  {selectedDeployment.source_type === "github" ? (
                    <ActionButton label="Update From GitHub" disabled={actionId === selectedDeployment.id} onClick={() => redeployGithub(selectedDeployment.id)} />
                  ) : null}
                  <ActionButton label="Restart" disabled={actionId === selectedDeployment.id} onClick={() => runAction(selectedDeployment.id, "restart")} />
                  <ActionButton label="Stop" disabled={actionId === selectedDeployment.id} onClick={() => runAction(selectedDeployment.id, "stop")} />
                  <button
                    onClick={() => runAction(selectedDeployment.id, "delete")}
                    disabled={actionId === selectedDeployment.id}
                    className="h-8 rounded-md border border-rose-200 px-3 text-xs font-bold text-rose-600 hover:bg-rose-50 transition disabled:opacity-50"
                  >
                    Delete
                  </button>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <DetailMetric label="Ingress Ports" value={selectedPorts.join(", ")} />
                <DetailMetric label="Target Port" value={selectedDeployment.internal_port} />
                <DetailMetric label="Instances" value={`${selectedPorts.length} ${selectedDeployment.scale_mode === "auto" ? "auto" : "manual"}`} />
                <DetailMetric label="Storage Cap" value={`${selectedDeployment.storage_limit_mb} MB`} />
              </div>

              {selectedDeployment.source_type === "github" ? (
                <div className="rounded-lg border border-zinc-200 bg-zinc-50 p-3 text-xs">
                  <div className="grid gap-2 sm:grid-cols-2">
                    <DetailMetric label="GitHub Repo" value={selectedDeployment.github_repo_url || "Not linked"} />
                    <DetailMetric label="Branch" value={selectedDeployment.github_branch || "main"} />
                    <DetailMetric label="Base Path" value={selectedDeployment.github_context_path || "."} />
                    <DetailMetric label="Deploy Mode" value={selectedDeployment.github_auto_deploy ? "Auto webhook" : "Manual update"} />
                    <DetailMetric label="Last Commit" value={selectedDeployment.github_last_commit?.slice(0, 12) || "Pending"} />
                  </div>
                  {selectedDeployment.github_auto_deploy && selectedDeployment.github_webhook_secret ? (
                    <div className="mt-3">
                      <div className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Webhook URL</div>
                      <div className="mt-1 break-all rounded border border-zinc-200 bg-white p-2 font-mono text-[11px] text-zinc-600">
                        {githubWebhookUrl(selectedDeployment.id, selectedDeployment.github_webhook_secret)}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}

              {selectedDeployment.last_error && (
                <div className="rounded-lg border border-rose-100 bg-rose-50 p-3 font-mono text-xs text-rose-700">
                  🛑 Error Context State: {selectedDeployment.last_error}
                </div>
              )}

              <div className="flex flex-wrap items-center gap-2 border-t border-zinc-100 pt-4">


                <a
                  href={loadBalancedDeploymentUrl(selectedDeployment.id)}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex h-8 items-center rounded-md border border-emerald-200 bg-emerald-50 px-3 text-xs font-semibold text-emerald-700 hover:bg-emerald-100/70 transition"
                >
                  Common Api
                </a>
                {selectedPortLinks.map(({ port, label }) => (
                  <a
                    key={port}
                    href={loadBalancedDeploymentUrl(selectedDeployment.id, "", port)}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex h-8 items-center rounded-md border border-zinc-200 bg-white px-3 text-xs font-semibold text-zinc-700 hover:bg-zinc-50 transition"
                  >
                    {label}
                  </a>
                ))}
              </div>
            </div>

            {/* Split Isolation: Clean Runtime Stats Subpanel */}
            <div className="rounded-xl border !border-orange-500 bg-white p-5 shadow-sm space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-500">Live Telemetry Metrics</h2>
              <div>  
                <button
                  onClick={() => refreshStats().catch((error) => alert(getErrorMessage(error)))}
                  className="h-8 rounded-md px-3 text-xs border border-zinc-200 font-semibold  hover:bg-zinc-800 transition"
                >
                  Sync Stats
                </button>
                <select
                  value={effectiveTelemetryView}
                  onChange={(event) => setTelemetryView(event.target.value)}
                  className="h-8 rounded-md border border-zinc-200 bg-zinc-50 px-2 text-xs font-semibold text-zinc-700 outline-none focus:border-cyan-600"
                >
                  <option value="all">All instances</option>
                  {instanceStats.map((item) => (
                    <option key={item.container_id} value={String(item.instance_index)}>
                      Instance {item.instance_index} :{item.assigned_port}
                    </option>
                  ))}
                </select>
                </div>

              </div>
              {telemetryStats ? (
                <div className="space-y-4">
                  <UsageBar
                    label={effectiveTelemetryView === "all" ? "Avg CPU Engine Load" : "CPU Engine Load"}
                    value={`${telemetryStats.cpu_usage_percent.toFixed(2)}%`}
                    percent={telemetryStats.cpu_usage_percent}
                    color="bg-cyan-700"
                  />
                  <UsageBar
                    label="Core Memory Bounds"
                    value={`${bytesToMb(telemetryStats.ram_usage_bytes)} / ${bytesToMb(telemetryStats.ram_limit_bytes)}`}
                    percent={telemetryStats.ram_limit_bytes > 0 ? (telemetryStats.ram_usage_bytes / telemetryStats.ram_limit_bytes) * 100 : 0}
                    color="bg-emerald-600"
                  />
                  <dl className="grid grid-cols-2 gap-2 border-t border-zinc-100 pt-3 text-xs">
                    <StatItem label="Active Runtime" value={formatRuntime(telemetryStats.uptime_seconds)} />
                    <StatItem
                      label="State Alive"
                      value={
                        effectiveTelemetryView === "all" && instanceStats.length > 0
                          ? `${instanceStats.filter((item) => item.running).length}/${instanceStats.length} Active`
                          : telemetryStats.running
                            ? "Active"
                            : "Halted"
                      }
                    />
                    <StatItem label="Panic Count" value={telemetryStats.restart_count} />
                    <StatItem label="Sample Clock" value={telemetryStats.collected_at ? new Date(telemetryStats.collected_at).toLocaleTimeString() : "Now"} />
                  </dl>
                  {effectiveTelemetryView === "all" && instanceStats.length > 0 ? (
                    <div className="grid gap-2 border-t border-zinc-100 pt-3 text-xs">
                      {instanceStats.map((item) => (
                        <div key={item.container_id} className="grid grid-cols-[80px_1fr_auto] items-center gap-2 rounded-md bg-zinc-50 px-3 py-2">
                          <span className="font-semibold text-zinc-700">Inst {item.instance_index}</span>
                          <span className="font-mono text-zinc-500">:{item.assigned_port}</span>
                          <span className="font-mono text-zinc-800">{item.cpu_usage_percent.toFixed(2)}% / {bytesToMb(item.ram_usage_bytes)}</span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                  {selectedInstanceStats ? (
                    <p className="break-all border-t border-zinc-100 pt-3 font-mono text-[11px] text-zinc-400">
                      {selectedInstanceStats.container_id}
                    </p>
                  ) : null}
                </div>
              ) : (
                <p className="text-xs leading-relaxed text-zinc-400 flex h-[160px] items-center justify-center text-center border border-dashed border-zinc-200 rounded-lg p-4 bg-zinc-50/30">
                  Execute diagnostics sync inside node space to generate detailed active consumption frameworks.
                </p>
              )}
            </div>
          </div>



          {/* Section: Diagnostics Execution & Stream Log Hub */}
          <div className="flex flex-col gap-4 rounded-2xl border !border-orange-500 p-5 shadow-xl ring-1 ring-white/5">
              {/* Unified Log Control Bar */}
              <div className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-800 pb-4">
                
                {/* Left Side: View Toggle & Main Actions */}
                <div className="flex flex-wrap items-center gap-2">
                  {/* View Mode Segmented Picker */}
                  <div className="flex rounded-lg  p-1 ring-1 ring-white/5">
                    <button
                      onClick={() => setViewMode("fetch")}
                      className={`rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all ${
                        viewMode === "fetch"
                          ? "!bg-zinc-800 text-white shadow"
                          : "text-zinc-400 hover:text-zinc-200"
                      }`}
                    >
                      Fetched Logs
                    </button>
                    
                    <button
                      onClick={() => setViewMode("live")}
                      className={`relative rounded-md px-3.5 py-1.5 text-xs font-semibold transition-all flex items-center gap-2 ${
                        viewMode === "live"
                          ? "!bg-zinc-800 text-white shadow"
                          : "text-zinc-400 hover:text-zinc-200"
                      }`}
                    >
                      Live Stream
                    </button>
                  </div>

                  {/* Dynamic Contextual Button based on active view mode */}
                  {viewMode === "fetch" ? (
                    <button
                      onClick={() => fetchLogs().catch((error) => alert(getErrorMessage(error)))}
                      className="inline-flex h-8 items-center justify-center rounded-lg border border-zinc-700 bg-zinc-800 px-3.5 text-xs font-semibold text-zinc-200 shadow-sm transition-colors hover:bg-zinc-700 hover:text-white"
                    >
                      Pull Latest
                    </button>
                  ) : (
                    <button
                      onClick={toggleStream}
                      className={`inline-flex h-8 items-center justify-center gap-1.5 rounded-lg border px-3.5 text-xs font-semibold shadow-sm transition-all ${
                        isStreaming
                          ? "border-rose-500/30 bg-rose-950/40 text-rose-400 hover:bg-rose-950/60"
                          : "border-cyan-500/30 bg-cyan-950/40 text-cyan-400 hover:bg-cyan-950/60"
                      }`}
                    >
                      {isStreaming ? "Disconnect" : "Connect Socket"}
                    </button>
                  )}
                </div>

                {/* Right Side: Scope Selector */}
                <div className="flex items-center gap-2.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">
                    Scope
                  </span>
                  <select
                    value={logTarget}
                    onChange={(event) => setLogTarget(event.target.value)}
                    className="h-8 rounded-lg border border-zinc-700 bg-zinc-800 px-2.5 text-xs font-semibold text-zinc-200 outline-none transition-colors focus:border-cyan-500"
                  >
                    <option value="all">All Instances</option>
                    {(selectedDeployment.container_ids?.length
                      ? selectedDeployment.container_ids
                      : [selectedDeployment.container_id]
                    )
                      .filter(Boolean)
                      .map((containerId, index) => (
                        <option key={containerId} value={String(index + 1)}>
                          Instance {index + 1}
                        </option>
                      ))}
                  </select>
                </div>
              </div>

              {/* Dedicated Single View Window */}
              <div className="w-full">
                {viewMode === "fetch" ? (
                  <LogPanel
                    title="Buffered Console Payload (REST)"
                    label={logTarget === "all" ? "All Instances" : `Instance ${logTarget}`}
                    content={logs || "Load container logs to print state framework maps."}
                  />
                ) : (
                  <LogPanel
                    title="Asynchronous Active Wire Stream"
                    label={isStreaming ? "Streaming Active" : "Socket Standby"}
                    content={
                      liveLogs.length
                        ? liveLogs.join("\n")
                        : "Establish active client socket listeners to stream line arrays live."
                    }
                    accent={isStreaming}
                  />
                )}
              </div>
            </div>


          {/* daily traffic and memory history. */}
            <DailyTrafficChart
              dailyStats={dailyStats}
              maxDailyRam={maxDailyRam}
              maxDailyRequests={maxDailyRequests}
              totalDailyRequests={totalDailyRequests}
              refreshDailyStats={refreshDailyStats}
              getErrorMessage={getErrorMessage}
              bytesToMb={bytesToMb}
            />

          {/* Section: Core Protected Isolated Console Terminal Executions */}
          <div className="rounded-xl border !border-orange-500 bg-white p-5 shadow-sm">
            <div className="mb-3 flex items-center justify-between border-b border-zinc-100 pb-3">
              <div>
                <h3 className="text-sm font-bold text-zinc-800">Secure Direct Node Shell Execution</h3>
                <p className="text-[11px] text-zinc-400 mt-0.5">Isolated runtime executor environment</p>
              </div>
              <span className="text-[10px] font-mono bg-zinc-100 px-2 py-0.5 rounded text-zinc-500">Sandbox Context: /app</span>
            </div>
            <textarea
              value={shellCommand}
              onChange={(event) => setShellCommand(event.target.value)}
              placeholder="e.g., cd internal && go build -o main main.go"
              className="h-16 w-full rounded-md border border-zinc-200 bg-zinc-50 p-3 font-mono text-xs text-zinc-800 outline-none focus:border-cyan-600 focus:bg-white transition"
            />
            <button
              onClick={runShellCommand}
              disabled={toolBusy}
              className="mt-2 h-8 rounded-md bg-zinc-950 px-4 text-xs font-semibold  hover:!bg-white disabled:opacity-50 transition"
            >
              Execute Command Script 
            </button>
            <pre className="mt-4 h-40 overflow-auto rounded-lg p-4 font-mono text-xs leading-5 text-white border border-zinc-800">
              {shellOutput || "# Execution architecture standard telemetry stream output window..."}
            </pre>
          </div>




        {/* Section: Local Network Binary / Ingestion Pipeline Injections */}
          <div className="rounded-xl border !border-orange-500 bg-zinc-50/50 p-5 border-dashed">
            <div>
              <h3 className="text-sm font-bold text-zinc-800">Add files to your deployment</h3>
              <p className="text-xs text-zinc-400 mt-0.5">Stream binary configurations or code objects directly inside target file containers.</p>
            </div>
            
            <div className="mt-4 grid gap-4 sm:grid-cols-3 items-end">
              <div className="space-y-1.5">
                <label className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Container Mount Pipeline Route</label>
                <input
                  value={uploadPath}
                  onChange={(event) => setUploadPath(event.target.value)}
                  placeholder="/app/resources/config.json"
                  className="h-9 w-full rounded-md border border-zinc-200 bg-white px-3 font-mono text-xs outline-none focus:border-cyan-600 transition"
                />
              </div>

              <div className="space-y-1.5">
                <label className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Local Resource Target Object</label>
                <input
                  type="file"
                  onChange={(event) => setContainerUpload(event.target.files?.[0] ?? null)}
                  className="block h-9 w-full rounded-md border border-zinc-200 bg-white px-3 py-1.5 text-xs text-zinc-500 file:mr-2 file:rounded file:border-0 file:bg-zinc-900 file:px-2.5 file:py-0.5 file:text-xs file:font-semibold file:text-white cursor-pointer"
                />
              </div>

              <div>
                <button
                  onClick={uploadFileToContainer}
                  disabled={toolBusy || !containerUpload || !uploadPath}
                  className="h-9 w-full rounded-md bg-zinc-950 text-xs font-semibold  hover:bg-zinc-800 disabled:opacity-40 transition shadow-sm"
                >
                  {toolBusy ? "Transferring Frameworks..." : "Inject Configuration Object Assets"}
                </button>
              </div>
            </div>
          </div>

          <div className="flex flex-col rounded-2xl border border-zinc-800 bg-black shadow-2xl ring-1 ring-white/5 overflow-hidden">
            
            {/* Unified Workspace Header */}
            <div className="flex flex-wrap items-center justify-between gap-4 border-b border-zinc-800 bg-zinc-950/40 p-5">
              <div>
                <h3 className="text-xs font-bold uppercase tracking-widest text-orange-400">
                  Workspace File Explorer
                </h3>
                <p className="mt-1 text-sm font-medium text-zinc-100">
                  Container Storage Space &amp; Editor
                </p>
              </div>
              
              {/* Scope/Status Indicator */}
              <div className="flex items-center gap-2 rounded-lg bg-zinc-950 px-3 py-1.5 border border-zinc-800">
                <span className="relative flex h-2 w-2">
                  <span className={`absolute inline-flex h-full w-full rounded-full opacity-75 ${toolBusy ? "animate-ping bg-amber-500" : "bg-orange-400"}`}></span>
                  <span className={`relative inline-flex rounded-full h-2 w-2 ${toolBusy ? "bg-amber-600" : "bg-orange-500"}`}></span>
                </span>
                <span className="font-mono text-[11px] font-semibold text-zinc-300">
                  {toolBusy ? "System Busy" : "File Tree Ready"}
                </span>
              </div>
            </div>

            {/* Sidebar Split Pane Layout */}
            <div className="grid md:grid-cols-5 divide-y md:divide-y-0 md:divide-x divide-zinc-800">
              
              {/* Left Column: Modern IDE File Tree Sidebar */}
              <div className="md:col-span-2 p-5 flex flex-col gap-4 bg-zinc-950/20">
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                    Directory Root Target
                  </label>
                  <div className="flex gap-2">
                    <input
                      value={filePath}
                      onChange={(event) => setFilePath(event.target.value)}
                      placeholder="/app"
                      className="h-9 flex-1 rounded-lg border border-zinc-800 bg-zinc-950 px-3 font-mono text-xs text-white outline-none transition-colors focus:border-orange-500"
                    />
                    <button
                      onClick={() => browseFiles()}
                      disabled={toolBusy}
                      className="h-9 rounded-lg border border-zinc-800 bg-zinc-900 px-3 text-xs font-semibold text-zinc-200 transition-all hover:bg-zinc-800 hover:text-white disabled:opacity-45"
                    >
                      Scan
                    </button>
                  </div>
                </div>

                {/* Hierarchical Tree Container */}
                <div className="flex flex-col gap-1.5 flex-1">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-500">
                    Navigation File Tree
                  </label>
                  
                  <div className="h-[320px] overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-950/60 p-2 [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden">
                    <div className="flex flex-col gap-0.5 font-mono text-xs">
                      
                      {fileEntries.map((entry) => {
                        const isDir = entry.kind === "directory";
                        const isActive = editorPath === entry.path;
                        
                        // Dynamically calculates depth indent logic if nested structure is present
                        const pathSegments = entry.path.replace(/^\/|\/$/g, "").split("/");
                        const depth = Math.max(0, pathSegments.length - 1);
                        const displayName = pathSegments[pathSegments.length - 1] || entry.path;

                        return (
                          <button
                            key={entry.path}
                            onClick={() => (isDir ? browseFiles(entry.path) : openFile(entry.path))}
                            style={{ paddingLeft: `${(depth * 12) + 8}px` }}
                            className={`group flex w-full items-center gap-2 rounded-md py-1.5 pr-2 text-left transition-all border border-transparent ${
                              isActive 
                                ? "bg-orange-950/40 text-orange-400 border-orange-500/20 font-medium" 
                                : "text-zinc-400 hover:bg-zinc-900/60 hover:text-zinc-100"
                            }`}
                          >
                            {/* Visual Structure Guide Connector Lines */}
                            {depth > 0 && (
                              <span className="text-zinc-800 font-normal tracking-tighter pointer-events-none -ml-1 mr-0.5">
                                │
                              </span>
                            )}

                            {/* Modern System File Tree Glyphs */}
                            {isDir ? (
                              <span className={`text-sm select-none ${isActive ? "text-amber-400" : "text-amber-600/80 group-hover:text-amber-500"}`}>
                                📁
                              </span>
                            ) : (
                              <span className={`text-sm select-none ${isActive ? "text-orange-400" : "text-zinc-600 group-hover:text-zinc-500"}`}>
                                📄
                              </span>
                            )}

                            {/* Clean Node Name Text */}
                            <span className="truncate flex-1 tracking-wide">
                              {displayName}
                            </span>
                          </button>
                        );
                      })}
                      
                      {fileEntries.length === 0 && (
                        <div className="py-12 text-center">
                          <span className="text-xl opacity-30 select-none">📭</span>
                          <p className="mt-2 text-xs text-zinc-500 italic">
                            No mount tree scanned yet.
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* Right Column: Integrated Code Workspace Editor View */}
              <div className="md:col-span-3 p-5 flex flex-col gap-4 bg-zinc-950/10">
                <div className="flex flex-col gap-1.5">
                  <label className="text-[10px] font-bold uppercase tracking-wider text-zinc-400">
                    Active Workspace Buffer File
                  </label>
                  <div className="flex gap-2">
                    <div className="relative flex-1 flex items-center">
                      <span className="absolute left-3 font-mono text-xs text-zinc-600 select-none">
                        EDIT:
                      </span>
                      <input
                        value={editorPath}
                        onChange={(event) => setEditorPath(event.target.value)}
                        placeholder="Select a node from navigation tree to edit"
                        className="h-9 w-full rounded-lg border border-zinc-800 bg-zinc-950 pl-14 pr-3 font-mono text-xs text-zinc-200 outline-none transition-colors focus:border-orange-500"
                      />
                    </div>
                    <button
                      onClick={saveFile}
                      disabled={toolBusy || !editorPath}
                      className="h-9 rounded-lg border border-orange-500/30 bg-orange-950/40 px-4 text-xs font-bold text-orange-400 transition-all hover:bg-orange-950 hover:border-orange-500 disabled:opacity-30 disabled:pointer-events-none"
                    >
                      Commit
                    </button>
                  </div>
                </div>

                {/* Textarea Code Area */}
                <div className="relative flex-1 flex flex-col">
                  <textarea
                    value={editorContent}
                    onChange={(event) => setEditorContent(event.target.value)}
                    placeholder="// Select a configuration file or dataset from the file explorer tree sidebar navigation grid to display stream content buffer variables live inside this block structure environment matrix layout framework."
                    className="h-[320px] w-full rounded-xl border border-zinc-800 bg-zinc-950 p-4 font-mono text-xs leading-6 text-zinc-200 outline-none transition-all focus:border-zinc-700 resize-none [scrollbar-width:none] [-ms-overflow-style:none] [&::-webkit-scrollbar]:hidden shadow-inner"
                  />
                  {/* Subtle Indicator Graphic Badge Overlay inside editor box */}
                  <div className="absolute bottom-3 right-4 pointer-events-none text-[9px] font-mono text-zinc-600 uppercase font-bold tracking-widest bg-zinc-900/80 px-1.5 py-0.5 rounded border border-zinc-800/60">
                    System Sync Buffer
                  </div>
                </div>
              </div>
              
            </div>
          </div>



        </div>
      ) : null}
    </section>
  );
}
