const SKIPPED_CONTEXT_DIRS = new Set([".git", "node_modules", ".next", "__pycache__", ".venv", "venv"]);

export function findDockerfile(files: File[]) {
  return files.find((file) => {
    const relativePath = getRelativeFilePath(file);
    return relativePath.split("/").pop() === "Dockerfile";
  }) ?? null;
}

export function buildTarContext(files: File[]) {
  const chunks: BlobPart[] = [];
  const selectedFiles = files
    .map((file) => ({ file, path: normalizeContextPath(getRelativeFilePath(file)) }))
    .filter(({ path }) => path && !shouldSkipContextPath(path));

  for (const { file, path } of selectedFiles) {
    chunks.push(tarHeader(path, file.size));
    chunks.push(file);
    chunks.push(new Uint8Array(paddingSize(file.size)));
  }

  chunks.push(new Uint8Array(1024));
  return new Blob(chunks, { type: "application/x-tar" });
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

function shouldSkipContextPath(path: string) {
  return path.split("/").some((part) => SKIPPED_CONTEXT_DIRS.has(part));
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
