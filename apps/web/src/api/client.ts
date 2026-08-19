/**
 * API 客户端：统一 fetch 封装（credentials include、错误归一化）。
 * 与 FastAPI 错误契约 {detail, code} 对齐。
 */
export interface ApiError {
  status: number
  detail: string
  code?: string
}

export class HttpError extends Error {
  status: number
  code?: string
  detail: string

  constructor(status: number, detail: string, code?: string) {
    super(detail)
    this.status = status
    this.code = code
    this.detail = detail
  }
}

export async function apiGet<T = unknown>(path: string): Promise<T> {
  const res = await fetch(path, { cache: 'no-store', credentials: 'include' })
  if (!res.ok) throw await toHttpError(res)
  return (await res.json()) as T
}

export async function apiPost<T = unknown>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    credentials: 'include',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) throw await toHttpError(res)
  return (await res.json()) as T
}

async function toHttpError(res: Response): Promise<HttpError> {
  try {
    const payload = (await res.json()) as { detail?: string; code?: string }
    return new HttpError(res.status, payload.detail || `HTTP ${res.status}`, payload.code)
  } catch {
    return new HttpError(res.status, `HTTP ${res.status}`)
  }
}
