export class ApiError extends Error {
  status: number;
  payload: unknown;
  retryAfterSeconds?: number;
  transient: boolean;

  constructor(
    message: string,
    status: number,
    payload: unknown,
    options: { retryAfterSeconds?: number; transient?: boolean } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload;
    this.retryAfterSeconds = options.retryAfterSeconds;
    this.transient = Boolean(options.transient);
  }
}

const TRANSIENT_STATUSES = new Set([408, 429, 502, 503, 504]);
const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_MAX_RETRY_DELAY_MS = 5000;
const DEFAULT_MAX_RETRY_AFTER_MS = 20_000;

function currentUiLang(): "zh" | "en" {
  if (typeof document !== "undefined") {
    const attr = document.documentElement?.dataset?.uiLang || document.documentElement?.lang || "";
    if (attr.toLowerCase().startsWith("en")) return "en";
  }
  try {
    if (typeof window !== "undefined" && window.localStorage?.getItem("ra-triage-lang") === "en") {
      return "en";
    }
  } catch {
    /* ignore storage errors */
  }
  return "zh";
}

function uiMsg(zh: string, en: string): string {
  return currentUiLang() === "en" ? en : zh;
}

export function parseRetryAfterSeconds(raw: string | null | undefined): number | undefined {
  if (!raw) return undefined;
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  if (/^\d+$/.test(trimmed)) {
    const secs = Number(trimmed);
    return Number.isFinite(secs) && secs >= 0 ? secs : undefined;
  }
  const timestamp = Date.parse(trimmed);
  if (Number.isFinite(timestamp)) {
    return Math.max(0, Math.ceil((timestamp - Date.now()) / 1000));
  }
  return undefined;
}

function friendlyTransientMessage(status: number, retryAfter?: number): string {
  if (status === 503) {
    if (retryAfter && retryAfter > 0) {
      return uiMsg(
        `系统正在维护或升级，您的未保存草稿已保留，请约 ${retryAfter} 秒后重试。`,
        `Service is under maintenance. Your unsaved draft is preserved; please retry in about ${retryAfter}s.`,
      );
    }
    return uiMsg(
      "系统正在维护或升级，您的未保存草稿已保留，请稍后重试。",
      "Service is under maintenance. Your unsaved draft is preserved; please retry shortly.",
    );
  }
  if (status === 502 || status === 504) {
    return uiMsg(
      "服务正在切换或短暂不可用，您的未保存草稿已保留，请稍后重试。",
      "Service is switching or briefly unavailable. Your unsaved draft is preserved; please retry shortly.",
    );
  }
  return uiMsg(
    `请求暂时不可用 (${status})，您的未保存草稿已保留，请稍后重试。`,
    `Request temporarily unavailable (${status}). Your unsaved draft is preserved; please retry shortly.`,
  );
}

function hasIdempotencyHeader(headers: Record<string, string>): boolean {
  return Object.entries(headers).some(
    ([key, value]) => key.toLowerCase() === "idempotency-key" && String(value || "").trim().length > 0,
  );
}

function looksLikeHtml(contentType: string, text: string): boolean {
  if (contentType.toLowerCase().includes("text/html")) return true;
  const trimmed = text.trimStart().slice(0, 32).toLowerCase();
  return trimmed.startsWith("<!doctype html") || trimmed.startsWith("<html");
}

function sleepAbortable(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0) return Promise.resolve();
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason || Object.assign(new Error("Request cancelled"), { name: "AbortError" }));
      return;
    }
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal?.reason || Object.assign(new Error("Request cancelled"), { name: "AbortError" }));
    };
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    signal?.addEventListener("abort", onAbort, { once: true });
  });
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
  cache?: RequestCache;
  maxAttempts?: number;
  retryBaseDelayMs?: number;
  maxRetryDelayMs?: number;
  maxRetryAfterMs?: number;
}

export async function apiRequest<T>(path: string, options: ApiRequestOptions = {}): Promise<T> {
  const method = (options.method || "GET").toUpperCase() as NonNullable<ApiRequestOptions["method"]>;
  const base = getApiBasePath();
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const url = `${base}${normalizedPath}`;

  const headers: Record<string, string> = {
    Accept: "application/json",
    ...(options.headers || {}),
  };
  let body: BodyInit | undefined;
  if (options.body !== undefined) {
    if (typeof FormData !== "undefined" && options.body instanceof FormData) {
      body = options.body;
    } else {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(options.body);
    }
  }
  if (method !== "GET" && !headers["X-RA-Triage-Request"]) {
    headers["X-RA-Triage-Request"] = "browser-v1";
  }

  // TanStack Query owns retries and failureCount visibility for GET queries.
  // Only idempotent mutations (explicit Idempotency-Key) retry automatically
  // inside apiRequest unless the caller opts into maxAttempts explicitly.
  const canRetry = hasIdempotencyHeader(headers) || (options.maxAttempts !== undefined && options.maxAttempts > 1);
  const maxAttempts = canRetry
    ? Math.max(1, options.maxAttempts ?? DEFAULT_MAX_ATTEMPTS)
    : 1;
  const retryBaseDelayMs = options.retryBaseDelayMs ?? 300;
  const maxRetryDelayMs = options.maxRetryDelayMs ?? DEFAULT_MAX_RETRY_DELAY_MS;
  const maxRetryAfterMs = options.maxRetryAfterMs ?? DEFAULT_MAX_RETRY_AFTER_MS;

  let lastError: unknown = null;
  let waitedRetryAfterMs = 0;

  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    if (options.signal?.aborted) {
      throw options.signal.reason || Object.assign(new Error("Request cancelled"), { name: "AbortError" });
    }
    let response: Response;
    let text: string;
    try {
      response = await fetch(url, {
        method,
        headers,
        body,
        credentials: "same-origin",
        signal: options.signal,
        ...(options.cache ? { cache: options.cache } : {}),
      });
      text = await response.text();
    } catch (err) {
      if (options.signal?.aborted || (err as { name?: string })?.name === "AbortError") {
        throw err;
      }
      const networkError = new ApiError(
        uiMsg(
          "网络连接中断，未保存草稿已保留，请检查网络后重试。",
          "Connection interrupted. Your unsaved draft is preserved; please retry.",
        ),
        0,
        null,
        { transient: true },
      );
      lastError = networkError;
      if (!canRetry || attempt >= maxAttempts - 1) {
        throw networkError;
      }
      await sleepAbortable(Math.min(retryBaseDelayMs * (attempt + 1), maxRetryDelayMs), options.signal);
      continue;
    }

    const contentType = response.headers?.get("content-type") || "";
    const retryAfter = parseRetryAfterSeconds(response.headers?.get("retry-after"));
    const htmlBody = looksLikeHtml(contentType, text);

    if (response.redirected && htmlBody) {
      throw new ApiError(
        uiMsg("登录状态已失效，请重新登录后重试。", "Your session has expired. Sign in again and retry."),
        401,
        null,
        { transient: false },
      );
    }

    let parsed: unknown = null;
    if (text && !htmlBody) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = text;
      }
    }

    if (response.ok) {
      return parsed as T;
    }

    const transient = TRANSIENT_STATUSES.has(response.status);
    const jsonDetail =
      parsed && typeof parsed === "object" && "detail" in parsed
        ? String((parsed as { detail?: unknown }).detail || "").trim()
        : "";
    const payloadRetryAfter =
      parsed &&
      typeof parsed === "object" &&
      "retry_after" in parsed &&
      typeof (parsed as { retry_after?: unknown }).retry_after === "number" &&
      Number.isFinite((parsed as { retry_after?: number }).retry_after)
        ? Math.max(0, Math.ceil((parsed as { retry_after: number }).retry_after))
        : undefined;
    const effectiveRetryAfter = retryAfter !== undefined ? retryAfter : payloadRetryAfter;
    let message = jsonDetail;
    if (!message) {
      if (transient) {
        message = friendlyTransientMessage(response.status, effectiveRetryAfter);
      } else if (htmlBody) {
        message = uiMsg(`请求失败 (${response.status})`, `Request failed (${response.status})`);
      } else if (typeof parsed === "string" && parsed.trim()) {
        message = parsed.trim();
      } else {
        message = `HTTP ${response.status}`;
      }
    } else if (
      transient &&
      effectiveRetryAfter &&
      effectiveRetryAfter > 0 &&
      !message.includes(String(effectiveRetryAfter))
    ) {
      message = `${message} (${uiMsg(`请约 ${effectiveRetryAfter} 秒后重试`, `retry in ~${effectiveRetryAfter}s`)})`;
    }

    const apiErr = new ApiError(message, response.status, parsed, {
      retryAfterSeconds: effectiveRetryAfter,
      transient,
    });
    lastError = apiErr;

    if (!canRetry || !transient || attempt >= maxAttempts - 1) {
      throw apiErr;
    }

    if (effectiveRetryAfter !== undefined) {
      const requestedWaitMs = Math.max(0, effectiveRetryAfter * 1000);
      // Never truncate an explicit Retry-After to a shorter backoff that burns
      // all attempts before the maintenance window expires. Honor the full
      // server-requested delay when bounded, otherwise surface the exact wait
      // time immediately so the user can retry once maintenance ends.
      if (requestedWaitMs > maxRetryAfterMs || waitedRetryAfterMs + requestedWaitMs > maxRetryAfterMs) {
        throw apiErr;
      }
      waitedRetryAfterMs += requestedWaitMs;
      await sleepAbortable(requestedWaitMs, options.signal);
    } else {
      const delayMs = Math.min(retryBaseDelayMs * (attempt + 1), maxRetryDelayMs);
      await sleepAbortable(delayMs, options.signal);
    }
  }

  throw lastError instanceof Error
    ? lastError
    : new ApiError(uiMsg("请求失败，请稍后重试。", "Request failed. Please retry."), 0, null, {
        transient: true,
      });
}
