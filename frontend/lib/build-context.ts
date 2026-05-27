const DEFAULT_SKIPPED_CONTEXT_DIRS = new Set([".git", "node_modules", ".next", "__pycache__", ".venv", "venv"]);

export type BuildContextPreview = {
  dockerignoreFound: boolean;
  includedFiles: string[];
  ignoredFiles: string[];
  totalFiles: number;
  includedBytes: number;
};

export type BuildContextOverrides = {
  includePaths?: Iterable<string>;
  excludePaths?: Iterable<string>;
};

export function findDockerfile(files: File[]) {
  return files.find((file) => {
    const relativePath = getRelativeFilePath(file);
    return relativePath.split("/").pop() === "Dockerfile";
  }) ?? null;
}

export async function buildTarContext(files: File[], overrides: BuildContextOverrides = {}) {
  const selectedFiles = await selectContextFiles(files, overrides);
  const chunks: BlobPart[] = [];

  for (const { file, path } of selectedFiles) {
    chunks.push(tarHeader(path, file.size));
    chunks.push(file);
    chunks.push(new Uint8Array(paddingSize(file.size)));
  }

  chunks.push(new Uint8Array(1024));
  return new Blob(chunks, { type: "application/x-tar" });
}

export async function getBuildContextPreview(files: File[], overrides: BuildContextOverrides = {}): Promise<BuildContextPreview> {
  const entries = files
    .map((file) => ({ file, path: normalizeContextPath(getRelativeFilePath(file)) }))
    .filter(({ path }) => Boolean(path));
  const matcher = await dockerignoreMatcher(entries);
  const includePaths = new Set(overrides.includePaths ?? []);
  const excludePaths = new Set(overrides.excludePaths ?? []);
  const includedFiles: string[] = [];
  const ignoredFiles: string[] = [];
  let includedBytes = 0;

  for (const entry of entries) {
    const ignored = excludePaths.has(entry.path) || (!includePaths.has(entry.path) && matcher(entry.path));
    if (ignored) {
      ignoredFiles.push(entry.path);
    } else {
      includedFiles.push(entry.path);
      includedBytes += entry.file.size;
    }
  }

  includedFiles.sort();
  ignoredFiles.sort();

  return {
    dockerignoreFound: matcher.dockerignoreFound,
    includedFiles,
    ignoredFiles,
    totalFiles: entries.length,
    includedBytes,
  };
}

async function selectContextFiles(files: File[], overrides: BuildContextOverrides) {
  const entries = files
    .map((file) => ({ file, path: normalizeContextPath(getRelativeFilePath(file)) }))
    .filter(({ path }) => Boolean(path));
  const matcher = await dockerignoreMatcher(entries);
  const includePaths = new Set(overrides.includePaths ?? []);
  const excludePaths = new Set(overrides.excludePaths ?? []);
  return entries.filter(({ path }) => !excludePaths.has(path) && (includePaths.has(path) || !matcher(path)));
}

type DockerignoreMatcher = ((path: string) => boolean) & { dockerignoreFound: boolean };

async function dockerignoreMatcher(entries: Array<{ file: File; path: string }>): Promise<DockerignoreMatcher> {
  const dockerignore = entries.find(({ path }) => path === ".dockerignore");
  if (!dockerignore) {
    const matcher = ((path: string) => shouldSkipDefaultContextPath(path)) as DockerignoreMatcher;
    matcher.dockerignoreFound = false;
    return matcher;
  }

  const rules = parseDockerignore(await dockerignore.file.text());
  const matcher = ((path: string) => {
    let ignored = false;
    for (const rule of rules) {
      if (matchesDockerignoreRule(path, rule.pattern)) {
        ignored = !rule.negated;
      }
    }
    return ignored;
  }) as DockerignoreMatcher;
  matcher.dockerignoreFound = true;
  return matcher;
}

function parseDockerignore(content: string) {
  return content
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#") && line !== ".")
    .map((line) => {
      const negated = line.startsWith("!");
      const rawPattern = negated ? line.slice(1) : line;
      return { negated, pattern: rawPattern.replaceAll("\\", "/") };
    })
    .filter(({ pattern }) => Boolean(pattern));
}

function matchesDockerignoreRule(path: string, rawPattern: string) {
  const directoryPattern = rawPattern.endsWith("/");
  const anchored = rawPattern.startsWith("/");
  const pattern = rawPattern.replace(/^\/+/, "").replace(/\/+$/, "");
  if (!pattern) return false;

  if (!pattern.includes("/")) {
    return path.split("/").some((part, index, parts) => {
      const isLast = index === parts.length - 1;
      return wildcardMatch(part, pattern) || (directoryPattern && !isLast && wildcardMatch(part, pattern));
    });
  }

  const candidates = anchored ? [path] : pathSegments(path);
  return candidates.some((candidate) => wildcardMatch(candidate, pattern) || candidate.startsWith(`${pattern}/`));
}

function pathSegments(path: string) {
  const parts = path.split("/");
  return parts.map((_, index) => parts.slice(index).join("/"));
}

function getRelativeFilePath(file: File) {
  return (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
}

function normalizeContextPath(path: string) {
  const clean = path.replaceAll("\\", "/").replace(/^\/+/, "");
  const parts = clean.split("/").filter(Boolean);
  if (parts.length > 1) {
    parts.shift();
  }
  return parts.join("/");
}

function shouldSkipDefaultContextPath(path: string) {
  return path.split("/").some((part) => DEFAULT_SKIPPED_CONTEXT_DIRS.has(part));
}

function wildcardMatch(value: string, pattern: string) {
  const escaped = pattern.replace(/[.+^${}()|[\]\\]/g, "\\$&");
  const regex = escaped.replace(/\*\*/g, "\0").replace(/\*/g, "[^/]*").replace(/\?/g, "[^/]").replaceAll("\0", ".*");
  return new RegExp(`^${regex}$`).test(value);
}

function tarHeader(name: string, size: number) {
  const header = new Uint8Array(512);
  writeString(header, 0, 100, name);
  writeOctal(header, 100, 8, 0o644);
  writeOctal(header, 108, 8, 0);
  writeOctal(header, 116, 8, 0);
  writeOctal(header, 124, 12, size);
  writeOctal(header, 136, 12, Math.floor(Date.now() / 1000));
  header.fill(32, 148, 156);
  header[156] = "0".charCodeAt(0);
  writeString(header, 257, 6, "ustar");
  writeString(header, 263, 2, "00");

  let checksum = 0;
  for (const byte of header) {
    checksum += byte;
  }
  writeOctal(header, 148, 8, checksum);
  return header;
}

function writeString(buffer: Uint8Array, offset: number, length: number, value: string) {
  const encoded = new TextEncoder().encode(value);
  buffer.set(encoded.slice(0, length), offset);
}

function writeOctal(buffer: Uint8Array, offset: number, length: number, value: number) {
  const octal = value.toString(8).padStart(length - 1, "0").slice(0, length - 1);
  writeString(buffer, offset, length, octal);
}

function paddingSize(size: number) {
  const remainder = size % 512;
  return remainder === 0 ? 0 : 512 - remainder;
}
