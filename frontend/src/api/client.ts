/** 统一请求封装：拼后端地址、抛网络错误、给页脚留一句可读的说明。 */
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

/** 断线/服务端暂时不可用时重试这些状态；业务校验失败（4xx 其余）不重试。 */
const RETRY_STATUSES = new Set([408, 429, 500, 502, 503, 504])
const RETRY_DELAYS = [500, 1200, 2500]

export function request(path: string, init?: RequestInit): Promise<Response> {
  const url = path.startsWith('http') ? path : `${API_BASE}${path}`
  return fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  }).catch((error: unknown) => {
    const detail = error instanceof Error ? error.message : '请求未送达'
    throw new Error(`接口请求失败：${detail}`)
  })
}

export async function fetchJson<T>(path: string): Promise<T> {
  const response = await request(path)
  if (!response.ok) {
    throw new Error(`接口返回 ${response.status}，数据未更新`)
  }
  return (await response.json()) as T
}

export type JsonRequestOptions = RequestInit & {
  /** 断线/服务端抖动时的最大重试次数，默认 0；动作接口建议给 3。 */
  retries?: number
}

/** 发 JSON 请求并解析响应体；网络失败按指数退避重试，成功或业务失败均返回 body。 */
export async function requestJson<T = unknown>(
  path: string,
  options: JsonRequestOptions = {},
): Promise<{ response: Response; body: T }> {
  const { retries = 0, ...init } = options
  let attempt = 0
  for (;;) {
    try {
      const response = await request(path, init)
      if (response.ok || !RETRY_STATUSES.has(response.status) || attempt >= retries) {
        const body = (await response.json().catch(() => null)) as T
        return { response, body }
      }
    } catch (error) {
      // 请求没送达（断线）：还有重试机会就继续，把原因带到最后一次。
      if (attempt >= retries) {
        throw error
      }
    }
    await new Promise((resolve) => setTimeout(resolve, RETRY_DELAYS[Math.min(attempt, RETRY_DELAYS.length - 1)]))
    attempt += 1
  }
}

/** 从 4xx 响应体里取出后端说明，取不到再用兜底文案。 */
export async function explainFailure(response: Response, fallback: string): Promise<string> {
  try {
    const data = await response.json()
    const detail = (data as { detail?: unknown })?.detail
    if (typeof detail === 'string' && detail) {
      return detail
    }
  } catch {
    // 响应体不是 JSON，走兜底文案。
  }
  return `${fallback}（HTTP ${response.status}）`
}
