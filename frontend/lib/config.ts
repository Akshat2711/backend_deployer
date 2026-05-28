export const apiBase = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
export const instanceUrlTemplate = process.env.NEXT_PUBLIC_INSTANCE_URL_TEMPLATE ?? "";

export const tokenStorageKey = "server-rent-token";

export function instanceUrl(port: number) {
  if (instanceUrlTemplate) {
    return instanceUrlTemplate.replaceAll("{port}", String(port));
  }
  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:${port}`;
  }
  return `:${port}`;
}
