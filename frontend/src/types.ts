export type SentimentSummary = {
  POSITIVE?: number
  NEGATIVE?: number
  NEUTRAL?: number
}

export type Article = {
  id: string
  source: string
  source_type: string
  url: string
  title: string
  content: string
  published_at: string
  sentiment_label?: string | null
  event_type?: string | null
}

export type Summary = {
  ticker: string
  days: number
  total_articles: number
  sentiment: SentimentSummary
  avg_sentiment_compound: number
  event_types: Record<string, number>
  sources: Record<string, number>
}

export type SocialSourceStatus = {
  source: string
  access_mode: 'public_api' | 'api_key_required' | 'bot_token_required' | 'api_credentials_required' | 'session_cookie_required'
  configured: boolean
  enabled: boolean
  security_notes: string
  compliance_notes: string
}

export type SocialSummary = {
  ticker: string
  days: number
  total_social_articles: number
  sources: Record<string, number>
  public_sources: string[]
}

export type WatchlistItem = {
  ticker: string
  is_dual: boolean
  us_ticker?: string | null
}
