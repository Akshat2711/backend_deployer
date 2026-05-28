"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  createDeployment,
  createDockerfileDeployment,
  createGithubDeployment,
  deleteDeployment,
  getDeploymentDailyStats,
  execInDeployment,
  getDeploymentInstanceLogs,
  getDeploymentInstanceStats,
  getDeploymentLogs,
  getDeploymentStats,
  getMe,
  getResourcePool,
  listContainerFiles,
  listDeployments,
  logsWebSocketUrl,
  readContainerFile,
  redeployGithubDeployment,
  runDeploymentAction,
  uploadContainerFile,
  writeContainerFile,
} from "@/lib/api";
import { buildTarContext, findDockerfile, getBuildContextPreview, type BuildContextPreview } from "@/lib/build-context";
import { tokenStorageKey } from "@/lib/config";
import { getErrorMessage } from "@/lib/errors";
import type { DailyDeploymentStats, Deployment, DeploymentAction, DeployFormState, FileEntry, InstanceStats, ResourcePool, Stats, User } from "@/lib/types";
import { FleetMetric, PoolBar } from "./ui";
import DashboardSection from "./DashboardSection";

import Navbar from "@/components/global_ui/Navbar";

const initialDeployForm: DeployFormState = {
  source: "image",
  image_name: "nginx:alpine",
  github_repo_url: "",
  github_branch: "main",
  github_context_path: ".",
  github_auto_deploy: false,
  internal_port: "80",
  cpu_limit: "0.25",
  ram_limit: "128",
  storage_limit_mb: "512",
  scale_mode: "manual",
  desired_instances: "1",
  pids_limit: "64",
  read_only: "default",
};

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}

async function exposedPortFromDockerfile(file: File | null) {
  if (!file) return null;
  const dockerfile = await file.text();
  const match = dockerfile.match(/^\s*EXPOSE\s+(\d+)(?:\/tcp)?(?:\s|$)/im);
  return match ? match[1] : null;
}

export default function DashboardRoute() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [resourcePool, setResourcePool] = useState<ResourcePool | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [instanceStats, setInstanceStats] = useState<InstanceStats[]>([]);
  const [dailyStats, setDailyStats] = useState<DailyDeploymentStats[]>([]);
  const [logs, setLogs] = useState("");
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  const [logTarget, setLogTarget] = useState("all");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionId, setActionId] = useState<number | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [deployForm, setDeployForm] = useState<DeployFormState>(initialDeployForm);
  const [dockerfile, setDockerfile] = useState<File | null>(null);
  const [codeDirFiles, setCodeDirFiles] = useState<File[]>([]);
  const [extraContextFiles, setExtraContextFiles] = useState<File[]>([]);
  const [contextIncludedPaths, setContextIncludedPaths] = useState<Set<string>>(new Set());
  const [contextExcludedPaths, setContextExcludedPaths] = useState<Set<string>>(new Set());
  const [contextPreview, setContextPreview] = useState<BuildContextPreview | null>(null);
  
  // Drawer Panel Toggle State
  const [isPanelOpen, setIsPanelOpen] = useState(false);

  // Shared states for interactive workspace sections
  const [shellCommand, setShellCommand] = useState("pwd && ls -la");
  const [shellOutput, setShellOutput] = useState("");
  const [filePath, setFilePath] = useState("/app");
  const [fileEntries, setFileEntries] = useState<FileEntry[]>([]);
  const [editorPath, setEditorPath] = useState("/app");
  const [editorContent, setEditorContent] = useState("");
  const [uploadPath, setUploadPath] = useState("/app/");
  const [containerUpload, setContainerUpload] = useState<File | null>(null);
  const [toolBusy, setToolBusy] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);

  const selectedDeployment = useMemo(
    () => deployments.find((deployment) => deployment.id === selectedId) ?? deployments[0] ?? null,
    [deployments, selectedId],
  );

  const contextFiles = useMemo(() => [...codeDirFiles, ...extraContextFiles], [codeDirFiles, extraContextFiles]);

  useEffect(() => {
    let cancelled = false;
    if (deployForm.source !== "dockerfile" || contextFiles.length === 0) {
      return;
    }

    getBuildContextPreview(contextFiles, {
      includePaths: contextIncludedPaths,
      excludePaths: contextExcludedPaths,
    })
      .then((preview) => {
        if (!cancelled) setContextPreview(preview);
      })
      .catch((error) => {
        if (!cancelled) {
          setContextPreview(null);
          setMessage(getErrorMessage(error));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [contextExcludedPaths, contextFiles, contextIncludedPaths, deployForm.source]);

  async function refreshDeployments(activeToken = token) {
    if (!activeToken) return;
    const rows = await listDeployments(activeToken);
    setDeployments(rows);
    setSelectedId((current) => current ?? rows[0]?.id ?? null);
  }

  async function refreshResourcePool(activeToken = token) {
    if (!activeToken) return;
    setResourcePool(await getResourcePool(activeToken));
  }

  async function refreshStats(id = selectedDeployment?.id) {
    if (!token || !id) return;
    const [primaryStats, allInstanceStats, dailyRows] = await Promise.all([
      getDeploymentStats(token, id),
      getDeploymentInstanceStats(token, id),
      getDeploymentDailyStats(token, id),
    ]);
    setStats(primaryStats);
    setInstanceStats(allInstanceStats);
    setDailyStats(dailyRows);
  }

  async function refreshDailyStats(id = selectedDeployment?.id) {
    if (!token || !id) return;
    setDailyStats(await getDeploymentDailyStats(token, id));
  }

  async function fetchLogs(id = selectedDeployment?.id) {
    if (!token || !id) return;
    if (logTarget === "all") {
      const rows = await getDeploymentInstanceLogs(token, id);
      setLogs(
        rows
          .map((row) => {
            const port = row.assigned_port ? `:${row.assigned_port}` : "no port";
            return `===== Instance ${row.instance_index} (${port}) ${row.container_id.slice(0, 12)} =====\n${row.logs || "(no logs)"}`;
          })
          .join("\n\n"),
      );
      return;
    }

    const response = await getDeploymentLogs(token, id, 300, Number(logTarget));
    setLogs(response.logs);
  }

  function resetContextOverrides() {
    setContextIncludedPaths(new Set());
    setContextExcludedPaths(new Set());
  }

  function includeContextPath(path: string) {
    setContextIncludedPaths((current) => new Set(current).add(path));
    setContextExcludedPaths((current) => {
      const next = new Set(current);
      next.delete(path);
      return next;
    });
  }

  function excludeContextPath(path: string) {
    setContextExcludedPaths((current) => new Set(current).add(path));
    setContextIncludedPaths((current) => {
      const next = new Set(current);
      next.delete(path);
      return next;
    });
  }

  async function selectCodeDirectory(files: File[]) {
    setContextPreview(null);
    resetContextOverrides();
    setExtraContextFiles([]);
    setCodeDirFiles(files);

    const detectedDockerfile = findDockerfile(files);
    setDockerfile(detectedDockerfile);

    try {
      const exposedPort = await exposedPortFromDockerfile(detectedDockerfile);
      if (exposedPort) {
        setDeployForm((current) => ({ ...current, internal_port: exposedPort }));
      }
    } catch (error) {
      setMessage(getErrorMessage(error));
    }
  }

  async function handleDeploy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;

    setBusy(true);
    setMessage(deployForm.source === "image" ? "Creating deployment. Pulling images can take a moment." : "Building deployment image. This can take a moment.");

    const payload: Record<string, string | number | boolean> = {
      image_name: deployForm.image_name,
      github_repo_url: deployForm.github_repo_url,
      github_branch: deployForm.github_branch,
      github_context_path: deployForm.github_context_path,
      github_auto_deploy: deployForm.github_auto_deploy,
      internal_port: Number(deployForm.internal_port),
      cpu_limit: Number(deployForm.cpu_limit),
      ram_limit: Number(deployForm.ram_limit),
      storage_limit_mb: Number(deployForm.storage_limit_mb),
      scale_mode: deployForm.scale_mode,
      desired_instances: Number(deployForm.desired_instances),
      pids_limit: Number(deployForm.pids_limit),
    };

    if (deployForm.read_only !== "default") {
      payload.read_only = deployForm.read_only === "true";
    }

    try {
      let deployment: Deployment;
      if (deployForm.source === "dockerfile") {
        const detectedDockerfile = dockerfile ?? findDockerfile(contextFiles);
        if (!detectedDockerfile) {
          throw new Error("Choose a Dockerfile or a code directory containing one.");
        }
        const formData = new FormData();
        formData.append("dockerfile", detectedDockerfile, "Dockerfile");
        if (contextFiles.length > 0) {
          formData.append(
            "context_archive",
            await buildTarContext(contextFiles, {
              includePaths: contextIncludedPaths,
              excludePaths: contextExcludedPaths,
            }),
            "build-context.tar",
          );
        }
        formData.append("internal_port", deployForm.internal_port);
        formData.append("cpu_limit", deployForm.cpu_limit);
        formData.append("ram_limit", deployForm.ram_limit);
        formData.append("storage_limit_mb", deployForm.storage_limit_mb);
        formData.append("scale_mode", deployForm.scale_mode);
        formData.append("desired_instances", deployForm.desired_instances);
        formData.append("pids_limit", deployForm.pids_limit);
        if (deployForm.read_only !== "default") {
          formData.append("read_only", deployForm.read_only);
        }
        deployment = await createDockerfileDeployment(token, formData);
      } else if (deployForm.source === "github") {
        deployment = await createGithubDeployment(token, payload);
      } else {
        deployment = await createDeployment(token, payload);
      }

      setDeployForm(initialDeployForm);
      setDockerfile(null);
      setCodeDirFiles([]);
      setExtraContextFiles([]);
      setContextIncludedPaths(new Set());
      setContextExcludedPaths(new Set());
      setContextPreview(null);
      setSelectedId(deployment.id);
      setIsPanelOpen(false); // Close side panel upon completion
      await refreshDeployments(token);
      await refreshResourcePool(token);
      setMessage(`Deployment #${deployment.id} is ${deployment.status}.`);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }

  async function runAction(id: number, action: DeploymentAction) {
    if (!token) return;
    setActionId(id);
    setMessage("");

    try {
      if (action === "delete") {
        await deleteDeployment(token, id);
        setSelectedId(null);
        setLogs("");
        setLiveLogs([]);
        setStats(null);
        setInstanceStats([]);
      } else {
        await runDeploymentAction(token, id, action);
      }
      await refreshDeployments(token);
      await refreshResourcePool(token);
      setMessage(`Deployment #${id} ${action === "delete" ? "deleted" : `${action}ed`}.`);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setActionId(null);
    }
  }

  async function redeployGithub(id: number) {
    if (!token) return;
    setActionId(id);
    setMessage("Pulling latest GitHub code and rebuilding deployment.");
    try {
      await redeployGithubDeployment(token, id);
      await refreshDeployments(token);
      await refreshResourcePool(token);
      setMessage(`Deployment #${id} updated from GitHub.`);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setActionId(null);
    }
  }

  function toggleStream() {
    if (!selectedDeployment || !token) return;

    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
      setIsStreaming(false);
      return;
    }

    const streamInstance = logTarget === "all" ? 1 : Number(logTarget);
    const socket = new WebSocket(logsWebSocketUrl(token, selectedDeployment.id, streamInstance));
    socketRef.current = socket;
    setLiveLogs([]);
    setIsStreaming(true);

    socket.onmessage = (event) => {
      setLiveLogs((current) => [...current.slice(-400), event.data]);
    };
    socket.onerror = () => setMessage("Live log stream failed.");
    socket.onclose = () => {
      socketRef.current = null;
      setIsStreaming(false);
    };
  }

  function selectDeployment(id: number) {
    socketRef.current?.close();
    setSelectedId(id);
    setStats(null);
    setInstanceStats([]);
    setDailyStats([]);
    setLogs("");
    setLiveLogs([]);
    setShellOutput("");
    setFileEntries([]);
    setEditorContent("");
    setLogTarget("all");
  }

  async function runShellCommand() {
    if (!token || !selectedDeployment) return;
    setToolBusy(true);
    try {
      const result = await execInDeployment(token, selectedDeployment.id, shellCommand, "/app");
      setShellOutput(`exit ${result.exit_code}\n${result.output}`);
    } catch (error) {
      setShellOutput(getErrorMessage(error));
    } finally {
      setToolBusy(false);
    }
  }

  async function browseFiles(path = filePath) {
    if (!token || !selectedDeployment) return;
    setToolBusy(true);
    try {
      const result = await listContainerFiles(token, selectedDeployment.id, path, 1);
      setFilePath(result.path);
      setFileEntries(result.entries);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setToolBusy(false);
    }
  }

  async function openFile(path: string) {
    if (!token || !selectedDeployment) return;
    setToolBusy(true);
    try {
      const result = await readContainerFile(token, selectedDeployment.id, path, 1);
      setEditorPath(result.path);
      setEditorContent(result.content);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setToolBusy(false);
    }
  }

  async function saveFile() {
    if (!token || !selectedDeployment) return;
    setToolBusy(true);
    try {
      const result = await writeContainerFile(token, selectedDeployment.id, editorPath, editorContent);
      setEditorPath(result.path);
      setEditorContent(result.content);
      setMessage(`Saved ${result.path}`);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setToolBusy(false);
    }
  }

  async function uploadFileToContainer() {
    if (!token || !selectedDeployment || !containerUpload) return;
    const targetPath = uploadPath.endsWith("/") ? `${uploadPath}${containerUpload.name}` : uploadPath;
    setToolBusy(true);
    try {
      const result = await uploadContainerFile(token, selectedDeployment.id, targetPath, containerUpload);
      setEditorPath(result.path);
      setEditorContent(result.content);
      setMessage(`Uploaded ${result.path}`);
      await browseFiles(filePath);
    } catch (error) {
      setMessage(getErrorMessage(error));
    } finally {
      setToolBusy(false);
    }
  }

  function signOut() {
    socketRef.current?.close();
    localStorage.removeItem(tokenStorageKey);
    router.push("/login");
  }

  useEffect(() => {
    const savedToken = localStorage.getItem(tokenStorageKey);
    if (!savedToken) {
      router.replace("/login");
      return;
    }

    queueMicrotask(() => {
      setToken(savedToken);
      getMe(savedToken)
        .then(setUser)
        .catch(() => {
          localStorage.removeItem(tokenStorageKey);
          router.replace("/login");
        });
    });
  }, [router]);

  useEffect(() => {
    if (!token || !user) return;
    Promise.all([listDeployments(token), getResourcePool(token)])
      .then(([rows, pool]) => {
        setDeployments(rows);
        setSelectedId((current) => current ?? rows[0]?.id ?? null);
        setResourcePool(pool);
      })
      .catch((error) => {
        setMessage(getErrorMessage(error));
      });
  }, [token, user]);

  useEffect(() => {
    return () => socketRef.current?.close();
  }, []);

  useEffect(() => {
    const deploymentId = selectedDeployment?.id;
    if (!token || !deploymentId) return;
    getDeploymentDailyStats(token, deploymentId)
      .then(setDailyStats)
      .catch((error) => setMessage(getErrorMessage(error)));
  }, [selectedDeployment?.id, token]);

  if (!user) {
    return (
      <main className="terminal-root flex min-h-screen items-center justify-center px-5 text-sm">
        booting dashboard...
      </main>
    );
  }

  return (
    <main className="terminal-root min-h-screen bg-zinc-50/50 text-zinc-950 antialiased">
      {/* Backdrop for Slide-over Drawer Panel */}
      {isPanelOpen && (
        <div 
          className="fixed inset-0 z-40 bg-zinc-950/20 backdrop-blur-sm transition-opacity"
          onClick={() => setIsPanelOpen(false)}
        />
      )}

      {/* Dynamic Slide-over Creation Draw Panel */}
      <div className={`fixed inset-y-0 right-0 z-50 w-full sm:max-w-md transform border-l border-zinc-200 bg-white p-4 sm:p-6 shadow-2xl transition-transform duration-300 ease-in-out ${isPanelOpen ? "translate-x-0" : "translate-x-full"}`}>
        <div className="flex items-center justify-between border-b border-zinc-100 pb-4">
          <div>
            <span className="text-xs font-mono tracking-widest text-zinc-400 uppercase">Config Spec</span>
            <h2 className="text-lg font-bold uppercase tracking-tight text-zinc-900">New Deployment</h2>
          </div>
          <button 
            onClick={() => setIsPanelOpen(false)}
            className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700 focus:outline-none"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleDeploy} className="mt-6 space-y-5 overflow-y-auto h-[calc(100vh-120px)] pr-1">
          <div className="flex rounded-lg bg-zinc-100 p-1">
            {(["image", "dockerfile", "github"] as const).map((source) => (
              <button
                key={source}
                type="button"
                onClick={() => {
                  setDeployForm({ ...deployForm, source });
                  if (source === "image") {
                    setContextPreview(null);
                    resetContextOverrides();
                  }
                }}
                className={`h-8 flex-1 rounded-md px-1 sm:px-3 text-[10px] sm:text-xs font-semibold capitalize transition truncate ${
                  deployForm.source === source ? "bg-white text-zinc-950 shadow-sm" : "text-zinc-500 hover:text-zinc-800"
                }`}
              >
                {source === "image" ? "Docker" : source === "github" ? "GitHub" : "Dockerfile"}
              </button>
            ))}
          </div>

          {deployForm.source === "image" ? (
            <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
              Image Reference
              <input
                required
                value={deployForm.image_name}
                onChange={(event) => setDeployForm({ ...deployForm, image_name: event.target.value })}
                className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 font-mono text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
                placeholder="nginx:alpine"
              />
            </label>
          ) : deployForm.source === "github" ? (
            <div className="space-y-3">
              <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
                GitHub Repository URL
                <input
                  required
                  value={deployForm.github_repo_url}
                  onChange={(event) => setDeployForm({ ...deployForm, github_repo_url: event.target.value })}
                  className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 font-mono text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
                  placeholder="https://github.com/owner/repo"
                />
              </label>
              <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
                Branch
                <input
                  required
                  value={deployForm.github_branch}
                  onChange={(event) => setDeployForm({ ...deployForm, github_branch: event.target.value })}
                  className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 font-mono text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
                  placeholder="main"
                />
              </label>
              <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
                Base Path
                <input
                  required
                  value={deployForm.github_context_path}
                  onChange={(event) => setDeployForm({ ...deployForm, github_context_path: event.target.value })}
                  className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 font-mono text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
                  placeholder="backend or frontend"
                />
              </label>
              <label className="flex items-center justify-between gap-3 rounded-md border border-zinc-200 bg-zinc-50 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-600">
                Auto Deploy New Changes
                <input
                  type="checkbox"
                  checked={deployForm.github_auto_deploy}
                  onChange={(event) => setDeployForm({ ...deployForm, github_auto_deploy: event.target.checked })}
                  className="h-4 w-4 accent-cyan-700"
                />
              </label>
            </div>
          ) : (
            <div className="space-y-2">
              <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">Code Directory Context</label>
              <input
                required
                type="file"
                multiple
                {...{ webkitdirectory: "", directory: "" }}
                onChange={(event) => {
                  const files = Array.from(event.target.files ?? []);
                  void selectCodeDirectory(files);
                }}
                className="block w-full rounded-md border border-zinc-200 px-3 py-2 text-xs file:mr-3 file:rounded file:border-0 file:bg-zinc-950 file:px-3 file:py-1 file:text-xs file:font-semibold file:text-white cursor-pointer"
              />
              <span className="block text-[11px] leading-relaxed text-zinc-400">
                Upload target project catalog containing your Dockerfile. Context compression generates automatically.
              </span>
              <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
                Add Files
                <input
                  type="file"
                  multiple
                  onChange={(event) => {
                    setExtraContextFiles((current) => [...current, ...Array.from(event.target.files ?? [])]);
                    event.currentTarget.value = "";
                  }}
                  className="mt-2 block w-full rounded-md border border-zinc-200 px-3 py-2 text-xs file:mr-3 file:rounded file:border-0 file:bg-zinc-700 file:px-3 file:py-1 file:text-xs file:font-semibold file:text-white cursor-pointer"
                />
              </label>
              {contextPreview ? (
                <div className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 sm:gap-3">
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-zinc-500">
                      Context Preview
                    </span>
                    <span className="text-[11px] text-zinc-400">
                      {contextPreview.includedFiles.length} / {contextPreview.totalFiles} files · {formatBytes(contextPreview.includedBytes)}
                    </span>
                  </div>
                  <div className="mt-1 text-[11px] text-zinc-500">
                    {contextPreview.dockerignoreFound ? ".dockerignore rules applied" : "Default generated-context excludes applied"}
                    {contextPreview.ignoredFiles.length > 0 ? ` · ${contextPreview.ignoredFiles.length} ignored` : ""}
                  </div>
                  <div className="mt-3 max-h-28 overflow-y-auto rounded border border-zinc-200 bg-white p-2 font-mono text-[11px] leading-5 text-zinc-600">
                    {contextPreview.includedFiles.slice(0, 12).map((path) => (
                      <div key={path} className="flex items-center justify-between gap-2">
                        <span className="truncate">{path}</span>
                        <button
                          type="button"
                          onClick={() => excludeContextPath(path)}
                          className="shrink-0 rounded px-1.5 py-0.5 font-sans text-[10px] font-semibold text-rose-600 hover:bg-rose-50"
                        >
                          remove
                        </button>
                      </div>
                    ))}
                    {contextPreview.includedFiles.length > 12 ? (
                      <div className="text-zinc-400">+{contextPreview.includedFiles.length - 12} more</div>
                    ) : null}
                  </div>
                  {contextPreview.ignoredFiles.length > 0 ? (
                    <div className="mt-2 max-h-20 overflow-y-auto rounded border border-zinc-200 bg-white p-2 font-mono text-[11px] leading-5 text-zinc-400">
                      {contextPreview.ignoredFiles.slice(0, 8).map((path) => (
                        <div key={path} className="flex items-center justify-between gap-2">
                          <span className="truncate">{path}</span>
                          <button
                            type="button"
                            onClick={() => includeContextPath(path)}
                            className="shrink-0 rounded px-1.5 py-0.5 font-sans text-[10px] font-semibold text-cyan-700 hover:bg-cyan-50"
                          >
                            add
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
              Internal Port
              <input
                required
                type="number"
                min="1"
                max="65535"
                value={deployForm.internal_port}
                onChange={(event) => setDeployForm({ ...deployForm, internal_port: event.target.value })}
                className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
              />
            </label>
            <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
              CPU Cores Allocation
              <input
                required
                type="number"
                min="0.05"
                max="4"
                step="0.05"
                value={deployForm.cpu_limit}
                onChange={(event) => setDeployForm({ ...deployForm, cpu_limit: event.target.value })}
                className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
              />
            </label>
            <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
              RAM Cap (MB)
              <input
                required
                type="number"
                min="32"
                max="4096"
                value={deployForm.ram_limit}
                onChange={(event) => setDeployForm({ ...deployForm, ram_limit: event.target.value })}
                className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
              />
            </label>
            <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
              Storage Cap (MB)
              <input
                required
                type="number"
                min="16"
                max="32768"
                value={deployForm.storage_limit_mb}
                onChange={(event) => setDeployForm({ ...deployForm, storage_limit_mb: event.target.value })}
                className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
              />
            </label>
            <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
              Scale Mode
              <select
                value={deployForm.scale_mode}
                onChange={(event) => setDeployForm({ ...deployForm, scale_mode: event.target.value as DeployFormState["scale_mode"] })}
                className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
              >
                <option value="manual">Manual Instances</option>
                <option value="auto">Auto Scale</option>
              </select>
            </label>
            <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
              PID Threshold
              <input
                required
                type="number"
                min="16"
                max="1024"
                value={deployForm.pids_limit}
                onChange={(event) => setDeployForm({ ...deployForm, pids_limit: event.target.value })}
                className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
              />
            </label>
          </div>

          {deployForm.scale_mode === "manual" ? (
            <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
              Instance Count
              <input
                required
                type="number"
                min="1"
                max="8"
                value={deployForm.desired_instances}
                onChange={(event) => setDeployForm({ ...deployForm, desired_instances: event.target.value })}
                className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
              />
            </label>
          ) : null}

          <label className="block text-xs font-semibold tracking-wide text-zinc-600 uppercase">
            Filesystem Permission Model
            <select
              value={deployForm.read_only}
              onChange={(event) => setDeployForm({ ...deployForm, read_only: event.target.value as DeployFormState["read_only"] })}
              className="mt-2 h-10 w-full rounded-md border border-zinc-200 bg-zinc-50 px-3 text-sm outline-none focus:border-cyan-600 focus:bg-white transition"
            >
              <option value="default">Engine System Default</option>
              <option value="true">Read Only Mount</option>
              <option value="false">Read & Write Allowed</option>
            </select>
          </label>

          <button
            type="submit"
            disabled={busy}
            className="h-11 w-full rounded-md bg-cyan-700 px-4 text-sm font-semibold text-white transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:bg-zinc-300"
          >
            {busy ? "Deploying Cluster Node..." : deployForm.source === "dockerfile" ? "Build & Deploy Artifact" : "Initialize Live Image"}
          </button>
        </form>
      </div>

      <Navbar
        userEmail={user.email}
        onNewDeployment={() => setIsPanelOpen(true)}
        onSignOut={signOut}
      />

      {/* Primary Layout Engine Context Grid */}
      <div className="mx-auto grid w-full gap-6 px-4 py-6 grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)] sm:px-6">
        {/* Responsive Metrics Sidebar/Top bar */}
        <aside className="space-y-6 w-full order-1 lg:order-none">
          <div className="rounded-xl border !border-orange-500 bg-white p-4 sm:p-5">
            <div className="flex items-center justify-between gap-3 border-b border-zinc-100 pb-3">
              <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-500">Fleet Health</h2>
              <button
                onClick={() => refreshDeployments().catch((error) => setMessage(getErrorMessage(error)))}
                className="text-xs font-semibold text-cyan-700 hover:text-cyan-800"
              >
                Refresh
              </button>
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2">
              <FleetMetric label="Total" value={deployments.length} />
              <FleetMetric label="Active" value={deployments.filter((item) => item.status === "running").length} />
              <FleetMetric label="Failed" value={deployments.filter((item) => item.status === "failed").length} />
            </div>
          </div>

          <div className="rounded-xl border !border-orange-500 bg-white p-4 sm:p-5">
            <div className="flex items-center justify-between gap-3 border-b border-zinc-100 pb-3">
              <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-500">Platform Resource Pool</h2>
              <button
                onClick={() => refreshResourcePool().catch((error) => setMessage(getErrorMessage(error)))}
                className="text-xs font-semibold text-cyan-700 hover:text-cyan-800"
              >
                Check
              </button>
            </div>
            {resourcePool ? (
              <div className="mt-4 space-y-4">
                <PoolBar label="CPU" used={resourcePool.used_cpu} max={resourcePool.max_cpu} suffix=" cores" />
                <PoolBar label="RAM" used={resourcePool.used_ram_mb} max={resourcePool.max_ram_mb} suffix=" MB" />
                <PoolBar label="Storage" used={resourcePool.used_storage_mb} max={resourcePool.max_storage_mb} suffix=" MB" />
                <PoolBar label="PIDs" used={resourcePool.used_pids} max={resourcePool.max_pids} suffix="" />
                <div className="flex flex-col sm:flex-row sm:items-center justify-between border-t border-zinc-100 pt-3 gap-1 text-xs text-zinc-500">
                  <span>Node Allocation Capacity</span>
                  <span className="font-semibold text-zinc-800">{resourcePool.active_deployments} / {resourcePool.max_deployments}</span>
                </div>
              </div>
            ) : (
              <p className="mt-3 text-xs leading-relaxed text-zinc-400">Usage statistics pull dynamically during orchestration updates.</p>
            )}
          </div>
        </aside>

        {/* Workspace Display Core Content Block */}
        <div className="w-full min-w-0">
          <DashboardSection
            message={message}
            setMessage={setMessage}
            deployments={deployments}
            selectedDeployment={selectedDeployment}
            selectDeployment={selectDeployment}
            refreshDeployments={refreshDeployments}
            runAction={runAction}
            redeployGithub={redeployGithub}
            actionId={actionId}
            refreshStats={refreshStats}
            fetchLogs={fetchLogs}
            logTarget={logTarget}
            setLogTarget={setLogTarget}
            toggleStream={toggleStream}
            isStreaming={isStreaming}
            logs={logs}
            liveLogs={liveLogs}
            runShellCommand={runShellCommand}
            shellCommand={shellCommand}
            setShellCommand={setShellCommand}
            shellOutput={shellOutput}
            toolBusy={toolBusy}
            browseFiles={browseFiles}
            filePath={filePath}
            setFilePath={setFilePath}
            fileEntries={fileEntries}
            openFile={openFile}
            editorPath={editorPath}
            setEditorPath={setEditorPath}
            saveFile={saveFile}
            editorContent={editorContent}
            setEditorContent={setEditorContent}
            uploadPath={uploadPath}
            setUploadPath={setUploadPath}
            setContainerUpload={setContainerUpload}
            containerUpload={containerUpload}
            uploadFileToContainer={uploadFileToContainer}
            stats={stats}
            instanceStats={instanceStats}
            dailyStats={dailyStats}
            refreshDailyStats={refreshDailyStats}
          />
        </div>
      </div>
    </main>
  );
}