export type User = {
  id: number;
  email: string;
  is_active: boolean;
};

export type Deployment = {
  id: number;
  user_id: number;
  image_name: string;
  container_id: string | null;
  container_ids: string[] | null;
  status: string;
  cpu_limit: number;
  ram_limit: number;
  storage_limit_mb: number;
  pids_limit: number;
  scale_mode: "manual" | "auto";
  desired_instances: number;
  assigned_port: number;
  assigned_ports: number[] | null;
  internal_port: number;
  read_only: boolean;
  restart_count: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
};

export type Stats = {
  deployment_id: number;
  cpu_usage_percent: number;
  ram_usage_bytes: number;
  ram_limit_bytes: number;
  uptime_seconds: number;
  restart_count: number;
  running: boolean;
  collected_at: string | null;
};

export type InstanceStats = Stats & {
  instance_index: number;
  container_id: string;
  assigned_port: number;
};

export type ResourcePool = {
  max_cpu: number;
  used_cpu: number;
  available_cpu: number;
  max_ram_mb: number;
  used_ram_mb: number;
  available_ram_mb: number;
  max_storage_mb: number;
  used_storage_mb: number;
  available_storage_mb: number;
  max_pids: number;
  used_pids: number;
  available_pids: number;
  max_deployments: number;
  active_deployments: number;
};

export type ExecResult = {
  exit_code: number;
  output: string;
};

export type FileEntry = {
  path: string;
  kind: "file" | "directory";
};

export type FileList = {
  path: string;
  entries: FileEntry[];
};

export type FileRead = {
  path: string;
  content: string;
};

export type DeployFormState = {
  source: "image" | "dockerfile";
  image_name: string;
  internal_port: string;
  cpu_limit: string;
  ram_limit: string;
  storage_limit_mb: string;
  scale_mode: "manual" | "auto";
  desired_instances: string;
  pids_limit: string;
  read_only: "default" | "true" | "false";
};

export type DeploymentAction = "restart" | "stop" | "delete";
