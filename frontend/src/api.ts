export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch('/api' + path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    const text = await res.text()
    let message = text || res.statusText
    try {
      const payload = JSON.parse(text)
      if (typeof payload.detail === 'string') message = payload.detail
      else if (Array.isArray(payload.detail)) {
        message = payload.detail.map((d: any) => d?.msg).filter(Boolean).join('；') || message
      }
    } catch { /* 非 JSON 错误体，保留原文 */ }
    throw new Error(message)
  }
  if (res.status === 204) return undefined as T
  return res.json()
}
