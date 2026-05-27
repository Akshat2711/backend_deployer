import { apiBase } from "./config";
import { responseError } from "./errors";
import type { Deployment, DeploymentAction, ExecResult, FileList, FileRead, InstanceStats, ResourcePool, Stats, User } from "./types";

type AuthResponse = {
  access_token: string;
};

async function jsonRequest<T>(path: string, token?: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${apiBase}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });

  if (!response.ok) {
    throw await responseError(response, `Request failed with ${response.status}`);
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function signup(email: string, password: string) {
  return jsonRequest<User>("/auth/signup", undefined, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function login(email: string, password: string) {
  return jsonRequest<AuthResponse>("/auth/login", undefined, {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export function getMe(token: string) {
  return jsonRequest<User>("/auth/me", token);
}

export function listDeployments(token: string) {
  return jsonRequest<Deployment[]>("/deployments", token);
}

export function getResourcePool(token: string) {
  return jsonRequest<ResourcePool>("/resource-pool", token);
}

export function createDeployment(token: string, payload: Record<string, string | number | boolean>) {
  return jsonRequest<Deployment>("/deploy", token, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function createDockerfileDeployment(token: string, formData: FormData) {
  const response = await fetch(`${apiBase}/deploy/dockerfile`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });

  if (!response.ok) {
    throw await responseError(response, `Request failed with ${response.status}`);
  }

  return response.json() as Promise<Deployment>;
}

export function getDeploymentStats(token: string, id: number) {
  return jsonRequest<Stats>(`/deployment/${id}/stats`, token);
}

export function getDeploymentInstanceStats(token: string, id: number) {
  return jsonRequest<InstanceStats[]>(`/deployment/${id}/instances/stats`, token);
}

export function getDeploymentLogs(token: string, id: number, tail = 300) {
  return jsonRequest<{ logs: string }>(`/deployment/${id}/logs?tail=${tail}`, token);
}

export function execInDeployment(token: string, id: number, command: string, workdir?: string) {
  return jsonRequest<ExecResult>(`/deployment/${id}/exec`, token, {
    method: "POST",
    body: JSON.stringify({ command, workdir }),
  });
}

export function listContainerFiles(token: string, id: number, path = "/app") {
  return jsonRequest<FileList>(`/deployment/${id}/files?path=${encodeURIComponent(path)}`, token);
}

export function readContainerFile(token: string, id: number, path: string) {
  return jsonRequest<FileRead>(`/deployment/${id}/file?path=${encodeURIComponent(path)}`, token);
}

export function writeContainerFile(token: string, id: number, path: string, content: string) {
  return jsonRequest<FileRead>(`/deployment/${id}/file`, token, {
    method: "PUT",
    body: JSON.stringify({ path, content }),
  });
}

export async function uploadContainerFile(token: string, id: number, path: string, file: File) {
  const formData = new FormData();
  formData.append("path", path);
  formData.append("file", file);

  const response = await fetch(`${apiBase}/deployment/${id}/file/upload`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
    body: formData,
  });

  if (!response.ok) {
    throw await responseError(response, `Request failed with ${response.status}`);
  }

  return response.json() as Promise<FileRead>;
}

export function runDeploymentAction(token: string, id: number, action: Exclude<DeploymentAction, "delete">) {
  return jsonRequest<Deployment>(`/${action}/${id}`, token, { method: "POST" });
}

export function deleteDeployment(token: string, id: number) {
  return jsonRequest<void>(`/deployment/${id}`, token, { method: "DELETE" });
}

export function loadBalancedDeploymentUrl(id: number, path = "") {
  const routeUrl = new URL(apiBase);
  const normalizedPath = path ? `/${path.replace(/^\/+/, "")}` : "";
  routeUrl.pathname = `/deployment/${id}/route${normalizedPath}`;
  return routeUrl.toString();
}

export function logsWebSocketUrl(token: string, id: number) {
  const wsUrl = new URL(apiBase);
  wsUrl.protocol = wsUrl.protocol === "https:" ? "wss:" : "ws:";
  wsUrl.pathname = `/ws/logs/${id}`;
  wsUrl.search = new URLSearchParams({ token }).toString();
  return wsUrl;
}
