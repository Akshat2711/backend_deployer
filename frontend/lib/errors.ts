export function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : "Something went wrong";
}

export async function responseError(response: Response, fallback: string) {
  try {
    const body = await response.json();
    const detail = body.detail ?? fallback;
    return new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join(", ") : detail);
  } catch {
    return new Error(fallback);
  }
}
