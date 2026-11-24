export class ApiError extends Error {
  status: number;
  payload: unknown;

  constructor(message: string, status: number, payload: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
  }
}

export function getApiBasePath(): string {
  if (typeof window === "undefined") return "";
  const winBase = (window as unknown as { __RA_TRIAGE_BASE__?: string }).__RA_TRIAGE_BASE__;
  if (typeof winBase === "string") return winBase.replace(/\/+$/, "");
  const meta = document.querySelector<HTMLMetaElement>('meta[name="ra-triage-base"]')?.content || "";
  const cleaned = meta.replace(/\/+$/, "");
  if (
    cleaned &&
    (window.location.pathname === cleaned || window.location.pathname.startsWith(`${cleaned}/`))
  ) {
    return cleaned;
  }
  return "";
}

export interface ApiRequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const method = options.method || "GET";
  const base = getApiBasePath();
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${base}${normalizedPath}`;

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(options.headers || {}),
  };
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(options.body);
  }
  if (method !== "GET") {
    headers["X-RA-Triage-Request"] = "browser-v1";
  }

  const response = await fetch(url, {
    method,
    headers,
    body,
    credentials: "same-origin",
    signal: options.signal,
  });

  const text = await response.text();
  let parsed: unknown = null;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = text;
    }
  }

  if (!response.ok) {
    const detail =
      parsed && typeof parsed === "object" && "detail" in parsed
        ? String((parsed as { detail?: unknown }).detail || "")
        : typeof parsed === "string"
          ? parsed
          : "";
    throw new ApiError(detail || `HTTP ${response.status}`, response.status, parsed);
  }

  return parsed as T;
}
