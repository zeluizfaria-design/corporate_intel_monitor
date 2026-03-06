import type { Article, SocialSourceStatus, SocialSummary, Summary, WatchlistItem } from './types'

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) {
    const payload = await response.text()
    throw new Error(`${response.status} ${response.statusText} - ${payload.slice(0, 220)}`)
  }
  return response.json() as Promise<T>
}

function toQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined) return
    query.set(key, String(value))
  })
  const serialized = query.toString()
  return serialized ? `?${serialized}` : ''
}

export const api = {
  summary: (ticker: string, days: number) =>
    getJson<Summary>(`/articles/${encodeURIComponent(ticker)}/summary?days=${days}`),

  articles: (ticker: string, days: number, sourceType?: string) =>
    getJson<Article[]>(
      `/articles/${encodeURIComponent(ticker)}${toQuery({ days, source_type: sourceType })}`,
    ),

  socialSources: () => getJson<SocialSourceStatus[]>('/social/sources'),

  socialSummary: (ticker: string, days: number) =>
    getJson<SocialSummary>(`/social/${encodeURIComponent(ticker)}/summary?days=${days}`),

  watchlist: () => getJson<WatchlistItem[]>('/watchlist'),

  addWatchlist: async (item: { ticker: string; is_dual?: boolean; us_ticker?: string | null }) => {
    const response = await fetch('/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(item),
    })
    if (!response.ok) {
      const payload = await response.text()
      throw new Error(`${response.status} ${response.statusText} - ${payload.slice(0, 220)}`)
    }
    return response.json()
  },

  removeWatchlist: async (ticker: string) => {
    const response = await fetch(`/watchlist/${encodeURIComponent(ticker)}`, {
      method: 'DELETE',
    })
    if (!response.ok) {
      const payload = await response.text()
      throw new Error(`${response.status} ${response.statusText} - ${payload.slice(0, 220)}`)
    }
    return response.json()
  },

  exportCsvUrl: (ticker: string, days: number) =>
    `/export/${encodeURIComponent(ticker)}${toQuery({ days })}`,

  triggerCollection: async (ticker: string, daysBack = 30) => {
    const response = await fetch('/collect', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, days_back: daysBack }),
    })
    if (!response.ok) {
      const payload = await response.text()
      throw new Error(`${response.status} ${response.statusText} - ${payload.slice(0, 220)}`)
    }
    return response.json()
  },
}
