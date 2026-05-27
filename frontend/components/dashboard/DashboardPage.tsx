"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import {
  createDeployment,
  createDockerfileDeployment,
  deleteDeployment,
  execInDeployment,
  getDeploymentInstanceStats,
  getDeploymentLogs,
  getDeploymentStats,
  getMe,
  getResourcePool,
  listContainerFiles,
  listDeployments,
  logsWebSocketUrl,
  readContainerFile,
  runDeploymentAction,
  uploadContainerFile,
  writeContainerFile,
} from "@/lib/api";
import { buildTarContext, findDockerfile } from "@/lib/build-context";
import { tokenStorageKey } from "@/lib/config";
import { getErrorMessage } from "@/lib/errors";
import type { Deployment, DeploymentAction, DeployFormState, FileEntry, InstanceStats, ResourcePool, Stats, User } from "@/lib/types";
import { FleetMetric, PoolBar } from "./ui";
import DashboardSection from "./DashboardSection";

import Navbar from "@/components/global_ui/Navbar";

const initialDeployForm: DeployFormState = {
  source: "image",
  image_name: "nginx:alpine",
  internal_port: "80",
  cpu_limit: "0.25",
  ram_limit: "128",
  storage_limit_mb: "512",
  scale_mode: "manual",
  desired_instances: "1",
  pids_limit: "64",
  read_only: "default",
};

export default function DashboardRoute() {
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [deployments, setDeployments] = useState<Deployment[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [resourcePool, setResourcePool] = useState<ResourcePool | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [instanceStats, setInstanceStats] = useState<InstanceStats[]>([]);
  const [logs, setLogs] = useState("");
  const [liveLogs, setLiveLogs] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionId, setActionId] = useState<number | null>(null);
  const [isStreaming, setIsStreaming] = useState(false);
  const [deployForm, setDeployForm] = useState<DeployFormState>(initialDeployForm);
  const [dockerfile, setDockerfile] = useState<File | null>(null);
  const [codeDirFiles, setCodeDirFiles] = useState<File[]>([]);
  
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
    const [primaryStats, allInstanceStats] = await Promise.all([
      getDeploymentStats(token, id),
      getDeploymentInstanceStats(token, id),
    ]);
    setStats(primaryStats);
    setInstanceStats(allInstanceStats);
  }

  async function fetchLogs(id = selectedDeployment?.id) {
    if (!token || !id) return;
    const response = await getDeploymentLogs(token, id);
    setLogs(response.logs);
  }

  async function handleDeploy(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token) return;

    setBusy(true);
    setMessage(deployForm.source === "dockerfile" ? "Building Dockerfile image. This can take a moment." : "Creating deployment. Pulling images can take a moment.");

    const payload: Record<string, string | number | boolean> = {
      image_name: deployForm.image_name,
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
        const detectedDockerfile = dockerfile ?? findDockerfile(codeDirFiles);
        if (!detectedDockerfile) {
          throw new Error("Choose a Dockerfile or a code directory containing one.");
        }
        const formData = new FormData();
        formData.append("dockerfile", detectedDockerfile, "Dockerfile");
        if (codeDirFiles.length > 0) {
          formData.append("context_archive", buildTarContext(codeDirFiles), "build-context.tar");
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
      } else {
        deployment = await createDeployment(token, payload);
      }

      setDeployForm(initialDeployForm);
      setDockerfile(null);
      setCodeDirFiles([]);
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

  function toggleStream() {
    if (!selectedDeployment || !token) return;

    if (socketRef.current) {
      socketRef.current.close();
      socketRef.current = null;
      setIsStreaming(false);
      return;
    }

    const socket = new WebSocket(logsWebSocketUrl(token, selectedDeployment.id));
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
    setLogs("");
    setLiveLogs([]);
    setShellOutput("");
    setFileEntries([]);
    setEditorContent("");
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
      const result = await listContainerFiles(token, selectedDeployment.id, path);
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
      const result = await readContainerFile(token, selectedDeployment.id, path);
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
        .then(() => listDeployments(savedToken))
        .then((rows) => {
          setDeployments(rows);
          setSelectedId((current) => current ?? rows[0]?.id ?? null);
        })
        .then(() => getResourcePool(savedToken))
        .then(setResourcePool)
        .catch(() => {
          localStorage.removeItem(tokenStorageKey);
          router.replace("/login");
        });
    });
  }, [router]);

  useEffect(() => {
    return () => socketRef.current?.close();
  }, []);

  if (!user) {
    return (
      <main className="terminal-root flex min-h-screen items-center justify-center px-5 text-sm">
        booting dashboard...
      </main>
    );
  }

  return (
    <main className="terminal-root min-h-screen bg-zinc-50/50 text-zinc-950 antialiased">
      {/* Dynamic Slide-over Creation Draw Panel */}
      <div className={`fixed inset-y-0 right-0 z-50 w-full max-w-md transform border-l border-zinc-200 bg-white p-6 shadow-2xl transition-transform duration-300 ease-in-out ${isPanelOpen ? "translate-x-0" : "translate-x-full"}`}>
        <div className="flex items-center justify-between border-b border-zinc-100 pb-4">
          <div>
            <span className="text-xs font-mono tracking-widest text-zinc-400 uppercase">Config Spec</span>
            <h2 className="text-lg font-bold uppercase tracking-tight text-zinc-900">New Deployment</h2>
          </div>
          <button 
            onClick={() => setIsPanelOpen(false)}
            className="rounded-md p-1.5 text-zinc-400 hover:bg-zinc-100 hover:text-zinc-700"
          >
            ✕
          </button>
        </div>

        <form onSubmit={handleDeploy} className="mt-6 space-y-5 overflow-y-auto h-[calc(100vh-120px)] pr-1">
          <div className="flex rounded-lg bg-zinc-100 p-1">
            {(["image", "dockerfile"] as const).map((source) => (
              <button
                key={source}
                type="button"
                onClick={() => setDeployForm({ ...deployForm, source })}
                className={`h-8 flex-1 rounded-md px-3 text-xs font-semibold capitalize transition ${
                  deployForm.source === source ? "bg-white text-zinc-950 shadow-sm" : "text-zinc-500 hover:text-zinc-800"
                }`}
              >
                {source === "image" ? "Docker Image" : "Dockerfile Context"}
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
                  setCodeDirFiles(files);
                  setDockerfile(findDockerfile(files));
                }}
                className="block w-full rounded-md border border-zinc-200 px-3 py-2 text-xs file:mr-3 file:rounded file:border-0 file:bg-zinc-950 file:px-3 file:py-1 file:text-xs file:font-semibold file:text-white cursor-pointer"
              />
              <span className="block text-[11px] leading-relaxed text-zinc-400">
                Upload target project catalog containing your Dockerfile. Context compression generates automatically.
              </span>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
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
            className="h-11 w-full rounded-md bg-cyan-700 px-4 text-sm font-semibold transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:bg-zinc-300"
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
      <div className="mx-auto grid w-full gap-6 px-6 py-6 lg:grid-cols-[280px_minmax(0,1fr)]">
        {/* Simplified Status Metrics Sidebar */}
        <aside className="space-y-6">
          <div className="rounded-xl border !border-orange-500 bg-white p-5">
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

          <div className="rounded-xl border !border-orange-500 bg-white p-5">
            <div className="flex items-center justify-between gap-3 border-b border-zinc-100 pb-3">
              <h2 className="text-xs font-bold uppercase tracking-wider text-zinc-500">Resource Pool</h2>
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
                <div className="flex items-center justify-between border-t border-zinc-100 pt-3 text-xs text-zinc-500">
                  <span>Node Allocation Capacity</span>
                  <span className="font-semibold text-zinc-800">{resourcePool.active_deployments} / {resourcePool.max_deployments}</span>
                </div>
              </div>
            ) : (
              <p className="mt-3 text-xs leading-relaxed text-zinc-400">Usage statistics pull dynamically during orchestration updates.</p>
            )}
          </div>
        </aside>

        <DashboardSection
          message={message}
          setMessage={setMessage}
          deployments={deployments}
          selectedDeployment={selectedDeployment}
          selectDeployment={selectDeployment}
          refreshDeployments={refreshDeployments}
          runAction={runAction}
          actionId={actionId}
          refreshStats={refreshStats}
          fetchLogs={fetchLogs}
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
        />
      </div>
    </main>
  );
}
