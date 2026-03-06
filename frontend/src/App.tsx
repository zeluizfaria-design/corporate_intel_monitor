import { useEffect, useMemo, useState } from 'react'
import { api } from './api'
import type {
  Article,
  CollectionJob,
  CollectionJobStatus,
  SocialSourceStatus,
  SocialSummary,
  Summary,
  WatchlistItem,
} from './types'

type LoadState = 'idle' | 'loading' | 'ready' | 'error'
type FeedSort = 'published_desc' | 'published_asc' | 'source_asc' | 'title_asc'

const DEFAULT_TICKER = 'NVDA'
const FEED_PAGE_SIZE = 20
const COLLECTION_POLL_INTERVAL_MS = 300
const COLLECTION_MAX_POLLS = 30

function dayKey(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value.slice(0, 10)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  return `${year}-${month}-${day}`
}

function formatDay(value: string): string {
  try {
    return new Date(`${value}T12:00:00`).toLocaleDateString('pt-BR', {
      day: '2-digit',
      month: '2-digit',
    })
  } catch {
    return value
  }
}

function formatDate(value: string): string {
  try {
    return new Date(value).toLocaleString('pt-BR', {
      dateStyle: 'short',
      timeStyle: 'short',
    })
  } catch {
    return value
  }
}

function sourceTypeBadge(sourceType: string): string {
  if (sourceType === 'social') return 'badge-social'
  if (sourceType === 'insider_trade') return 'badge-insider'
  if (sourceType === 'politician_trade') return 'badge-political'
  if (sourceType === 'fato_relevante') return 'badge-material'
  return 'badge-news'
}

function sourceTypeLabel(sourceType: string): string {
  if (sourceType === 'social') return 'Social'
  if (sourceType === 'insider_trade') return 'Insider trade'
  if (sourceType === 'politician_trade') return 'Politician trade'
  if (sourceType === 'fato_relevante') return 'Fato relevante'
  return 'News'
}

function collectionStatusLabel(status: CollectionJobStatus): string {
  if (status === 'queued') return 'na fila'
  if (status === 'running') return 'em execucao'
  if (status === 'completed') return 'concluida'
  return 'falhou'
}

function collectionStatusClass(status: CollectionJobStatus): string {
  if (status === 'queued') return 'status-queued'
  if (status === 'running') return 'status-running'
  if (status === 'completed') return 'status-completed'
  return 'status-failed'
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

function getCollectorFailureCount(job: CollectionJob | null): number {
  if (!job || !job.summary || typeof job.summary !== 'object') return 0
  const value = (job.summary as Record<string, unknown>).collector_failures
  if (!Array.isArray(value)) return 0
  return value.length
}

export default function App() {
  const [ticker, setTicker] = useState(DEFAULT_TICKER)
  const [days, setDays] = useState(7)
  const [sourceFilter, setSourceFilter] = useState('')
  const [feedSort, setFeedSort] = useState<FeedSort>('published_desc')
  const [currentPage, setCurrentPage] = useState(1)
  const [isIdentityDialogOpen, setIsIdentityDialogOpen] = useState(false)
  const [loginEmail, setLoginEmail] = useState('')

  const [summary, setSummary] = useState<Summary | null>(null)
  const [articles, setArticles] = useState<Article[]>([])
  const [socialSources, setSocialSources] = useState<SocialSourceStatus[]>([])
  const [socialSummary, setSocialSummary] = useState<SocialSummary | null>(null)
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([])

  const [newWatchTicker, setNewWatchTicker] = useState('')
  const [newWatchIsDual, setNewWatchIsDual] = useState(false)
  const [newWatchUsTicker, setNewWatchUsTicker] = useState('')

  const [state, setState] = useState<LoadState>('idle')
  const [error, setError] = useState<string>('')
  const [collecting, setCollecting] = useState(false)
  const [watchlistLoading, setWatchlistLoading] = useState(false)
  const [watchlistBusy, setWatchlistBusy] = useState(false)
  const [collectionJob, setCollectionJob] = useState<CollectionJob | null>(null)
  const [collectionStatusRefreshing, setCollectionStatusRefreshing] = useState(false)
  const [panelLoading, setPanelLoading] = useState({
    summary: false,
    feed: false,
    socialSummary: false,
    socialSources: false,
  })
  const collectorFailureCount = useMemo(() => getCollectorFailureCount(collectionJob), [collectionJob])

  async function loadWatchlist() {
    setWatchlistLoading(true)
    try {
      const items = await api.watchlist()
      setWatchlist(items)
    } finally {
      setWatchlistLoading(false)
    }
  }

  async function loadAll(nextTicker: string, nextDays: number, nextSourceFilter = sourceFilter) {
    const firstLoad = state === 'idle'
    if (firstLoad) {
      setState('loading')
    }
    setError('')
    setPanelLoading({
      summary: true,
      feed: true,
      socialSummary: true,
      socialSources: true,
    })

    const [sumResult, articlesResult, sourcesResult, socialResult] = await Promise.allSettled([
      api.summary(nextTicker, nextDays),
      api.articles(nextTicker, nextDays, nextSourceFilter || undefined),
      api.socialSources(),
      api.socialSummary(nextTicker, nextDays),
    ])

    const errors: string[] = []

    if (sumResult.status === 'fulfilled') {
      setSummary(sumResult.value)
    } else {
      errors.push(`Resumo: ${sumResult.reason instanceof Error ? sumResult.reason.message : 'erro desconhecido'}`)
    }
    setPanelLoading((current) => ({ ...current, summary: false }))

    if (articlesResult.status === 'fulfilled') {
      setArticles(articlesResult.value)
      setCurrentPage(1)
    } else {
      errors.push(
        `Feed: ${articlesResult.reason instanceof Error ? articlesResult.reason.message : 'erro desconhecido'}`,
      )
    }
    setPanelLoading((current) => ({ ...current, feed: false }))

    if (sourcesResult.status === 'fulfilled') {
      setSocialSources(sourcesResult.value)
    } else {
      errors.push(
        `Fontes sociais: ${
          sourcesResult.reason instanceof Error ? sourcesResult.reason.message : 'erro desconhecido'
        }`,
      )
    }
    setPanelLoading((current) => ({ ...current, socialSources: false }))

    if (socialResult.status === 'fulfilled') {
      setSocialSummary(socialResult.value)
    } else {
      errors.push(
        `Resumo social: ${socialResult.reason instanceof Error ? socialResult.reason.message : 'erro desconhecido'}`,
      )
    }
    setPanelLoading((current) => ({ ...current, socialSummary: false }))

    if (errors.length > 0) {
      setError(errors.join(' | '))
      setState('error')
      return
    }

    setState('ready')
  }

  useEffect(() => {
    const savedEmail = window.localStorage.getItem('cim_research_login_email') ?? ''
    setLoginEmail(savedEmail)
    void Promise.all([loadAll(DEFAULT_TICKER, days, sourceFilter), loadWatchlist()]).catch((err) => {
      setError(err instanceof Error ? err.message : 'Falha ao carregar estado inicial.')
      setState('error')
    })
  }, [])

  const sentimentRows = useMemo(() => {
    if (!summary) return []
    return Object.entries(summary.sentiment || {})
  }, [summary])

  const socialTrendRows = useMemo(() => {
    if (!socialSummary) return []
    return Object.entries(socialSummary.sources || {}).sort((a, b) => b[1] - a[1])
  }, [socialSummary])

  const sentimentTimelineRows = useMemo(() => {
    const buckets = new Map<string, { positive: number; negative: number; neutral: number; total: number }>()

    articles.forEach((article) => {
      const key = dayKey(article.published_at)
      const current = buckets.get(key) ?? { positive: 0, negative: 0, neutral: 0, total: 0 }
      const label = (article.sentiment_label ?? '').toUpperCase()
      if (label === 'POSITIVE') current.positive += 1
      else if (label === 'NEGATIVE') current.negative += 1
      else current.neutral += 1
      current.total += 1
      buckets.set(key, current)
    })

    return [...buckets.entries()]
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([date, values]) => ({ date, ...values }))
  }, [articles])

  const eventPeriodRows = useMemo(() => {
    const fromSummary = summary ? Object.entries(summary.event_types || {}) : []
    if (fromSummary.length > 0) {
      return fromSummary.filter(([, count]) => count > 0).sort((a, b) => b[1] - a[1]).slice(0, 8)
    }

    const fallback = new Map<string, number>()
    articles.forEach((article) => {
      const event = (article.event_type ?? 'nao_classificado').trim() || 'nao_classificado'
      fallback.set(event, (fallback.get(event) ?? 0) + 1)
    })
    return [...fallback.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8)
  }, [summary, articles])

  const maxEventCount = useMemo(() => {
    return eventPeriodRows[0]?.[1] ?? 1
  }, [eventPeriodRows])

  const sortedArticles = useMemo(() => {
    const next = [...articles]
    if (feedSort === 'published_asc') {
      next.sort((a, b) => a.published_at.localeCompare(b.published_at))
      return next
    }
    if (feedSort === 'source_asc') {
      next.sort((a, b) => a.source.localeCompare(b.source))
      return next
    }
    if (feedSort === 'title_asc') {
      next.sort((a, b) => a.title.localeCompare(b.title))
      return next
    }
    next.sort((a, b) => b.published_at.localeCompare(a.published_at))
    return next
  }, [articles, feedSort])

  const totalPages = useMemo(() => {
    return Math.max(1, Math.ceil(sortedArticles.length / FEED_PAGE_SIZE))
  }, [sortedArticles.length])

  const pagedArticles = useMemo(() => {
    const start = (currentPage - 1) * FEED_PAGE_SIZE
    return sortedArticles.slice(start, start + FEED_PAGE_SIZE)
  }, [sortedArticles, currentPage])

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages)
    }
  }, [currentPage, totalPages])

  async function pollCollectionStatus(jobId: string): Promise<CollectionJob> {
    for (let attempt = 1; attempt <= COLLECTION_MAX_POLLS; attempt += 1) {
      const job = await api.collectionStatus(jobId)
      setCollectionJob(job)
      if (job.status === 'completed' || job.status === 'failed') {
        return job
      }
      await sleep(COLLECTION_POLL_INTERVAL_MS)
    }
    throw new Error(`Timeout ao acompanhar coleta ${jobId}.`)
  }

  async function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const next = ticker.trim().toUpperCase()
    if (!next) return
    setTicker(next)
    await loadAll(next, days, sourceFilter)
  }

  async function onRunCollection() {
    try {
      setCollecting(true)
      setError('')
      const trigger = await api.triggerCollection(ticker, 30)
      const job = await pollCollectionStatus(trigger.job_id)
      if (job.status === 'failed') {
        throw new Error(job.error || `Job ${job.job_id} falhou sem detalhe de erro.`)
      }
      await loadAll(ticker, days, sourceFilter)
    } catch (err) {
      setError(err instanceof Error ? `Falha ao disparar coleta: ${err.message}` : 'Falha ao disparar coleta.')
      setState('error')
    } finally {
      setCollecting(false)
    }
  }

  async function onRefreshCollectionStatus() {
    if (!collectionJob) return
    try {
      setCollectionStatusRefreshing(true)
      setError('')
      const latest = await api.collectionStatus(collectionJob.job_id)
      setCollectionJob(latest)
      if (latest.status === 'completed') {
        await loadAll(latest.ticker, days, sourceFilter)
        return
      }
      if (latest.status === 'failed') {
        setError(`Coleta ${latest.job_id} falhou: ${latest.error || 'erro desconhecido'}`)
        setState('error')
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? `Falha ao consultar status da coleta: ${err.message}`
          : 'Falha ao consultar status da coleta.',
      )
      setState('error')
    } finally {
      setCollectionStatusRefreshing(false)
    }
  }

  async function onAddWatchlist(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalizedTicker = newWatchTicker.trim().toUpperCase()
    if (!normalizedTicker) return

    try {
      setWatchlistBusy(true)
      await api.addWatchlist({
        ticker: normalizedTicker,
        is_dual: newWatchIsDual,
        us_ticker: newWatchIsDual ? newWatchUsTicker.trim().toUpperCase() || null : null,
      })
      await loadWatchlist()
      setNewWatchTicker('')
      setNewWatchUsTicker('')
      setNewWatchIsDual(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao adicionar ticker na watchlist.')
      setState('error')
    } finally {
      setWatchlistBusy(false)
    }
  }

  async function onRemoveWatchlist(removeTicker: string) {
    try {
      setWatchlistBusy(true)
      await api.removeWatchlist(removeTicker)
      await loadWatchlist()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Falha ao remover ticker da watchlist.')
      setState('error')
    } finally {
      setWatchlistBusy(false)
    }
  }

  function saveIdentityEmail() {
    const normalized = loginEmail.trim().toLowerCase()
    if (!normalized) {
      window.localStorage.removeItem('cim_research_login_email')
      setIsIdentityDialogOpen(false)
      return
    }
    window.localStorage.setItem('cim_research_login_email', normalized)
    setLoginEmail(normalized)
    setIsIdentityDialogOpen(false)
  }

  function maskEmail(value: string): string {
    const [name, domain] = value.split('@')
    if (!name || !domain) return value
    if (name.length <= 2) return `${name[0] ?? '*'}*@${domain}`
    return `${name[0]}${'*'.repeat(Math.max(name.length - 2, 1))}${name[name.length - 1]}@${domain}`
  }

  return (
    <main className="page">
      <header className="hero">
        <p className="eyebrow">Corporate Intelligence Monitor</p>
        <h1>Etapa P8: Dashboard React</h1>
        <p className="subtext">
          Foco em monitoramento corporativo e obtencao gratuita de dados sociais com compliance.
        </p>
      </header>

      <section className="panel control-panel">
        <form onSubmit={onSubmit} className="controls">
          <label>
            Ticker
            <input
              value={ticker}
              onChange={(event) => setTicker(event.target.value.toUpperCase())}
              placeholder="AAPL"
            />
          </label>
          <label>
            Janela (dias)
            <input
              type="number"
              min={1}
              max={90}
              value={days}
              onChange={(event) => setDays(Number(event.target.value || 7))}
            />
          </label>
          <label>
            Filtro de fonte
            <select value={sourceFilter} onChange={(event) => setSourceFilter(event.target.value)}>
              <option value="">Todas</option>
              <option value="news">News</option>
              <option value="social">Social</option>
              <option value="insider_trade">Insider trade</option>
              <option value="politician_trade">Politician trade</option>
              <option value="fato_relevante">Fato relevante</option>
            </select>
          </label>
          <button type="submit" disabled={state === 'loading'}>
            Consultar
          </button>
          <button type="button" onClick={onRunCollection} disabled={collecting}>
            {collecting ? 'Coletando...' : 'Coletar agora'}
          </button>
          <button type="button" onClick={() => window.open(api.exportCsvUrl(ticker, days), '_blank')}>
            Exportar CSV
          </button>
          <button type="button" onClick={() => setIsIdentityDialogOpen(true)}>
            Identidade de login
          </button>
        </form>

        <p className="note">
          Seguranca: credenciais ficam apenas no backend. Frontend nao usa chaves de API.
        </p>
        {collectionJob && (
          <section className="collection-status" role="status" aria-live="polite">
            <div className="row">
              <h3>Status da coleta</h3>
              <span className={`status-pill ${collectionStatusClass(collectionJob.status)}`}>
                {collectionStatusLabel(collectionJob.status)}
              </span>
            </div>
            <p className="note">
              Job: <strong>{collectionJob.job_id}</strong> | Ticker: <strong>{collectionJob.ticker}</strong> | Janela
              coleta: <strong>{collectionJob.days_back} dias</strong>
            </p>
            <p className="muted">
              Enfileirada em: {formatDate(collectionJob.queued_at)} | Inicio:{' '}
              {collectionJob.started_at ? formatDate(collectionJob.started_at) : '-'} | Fim:{' '}
              {collectionJob.finished_at ? formatDate(collectionJob.finished_at) : '-'}
            </p>
            <div className="collection-actions">
              <button
                type="button"
                className="btn-ghost"
                onClick={() => void onRefreshCollectionStatus()}
                disabled={collecting || collectionStatusRefreshing}
              >
                {collectionStatusRefreshing ? 'Atualizando status...' : 'Atualizar status'}
              </button>
            </div>
            {collectionJob.status === 'completed' && collectorFailureCount > 0 && (
              <p className="warning-inline">
                Coleta concluida com falhas parciais em {collectorFailureCount} coletor(es).
              </p>
            )}
            {collectionJob.error && <p className="error-inline">Falha: {collectionJob.error}</p>}
          </section>
        )}
        {loginEmail && (
          <p className="note">
            Email de apoio salvo localmente: <strong>{maskEmail(loginEmail)}</strong>
          </p>
        )}
      </section>

      {state === 'error' && <section className="panel error">Erro: {error}</section>}
      {state === 'loading' && <section className="panel">Carregando dados iniciais...</section>}

      {(state === 'ready' || state === 'error') && (
        <>
          <section className="grid metrics">
            <article className="panel metric">
              <h2>Total</h2>
              <p className="metric-value">{panelLoading.summary ? '...' : (summary?.total_articles ?? 0)}</p>
            </article>
            <article className="panel metric">
              <h2>Sentimento medio</h2>
              <p className="metric-value">
                {panelLoading.summary ? '...' : (summary?.avg_sentiment_compound ?? 0)}
              </p>
            </article>
            <article className="panel metric">
              <h2>Social coletado</h2>
              <p className="metric-value">
                {panelLoading.socialSummary ? '...' : (socialSummary?.total_social_articles ?? 0)}
              </p>
            </article>
          </section>

          <section className="panel">
            <h2>Watchlist</h2>
            <form className="watch-form" onSubmit={onAddWatchlist}>
              <label>
                Ticker
                <input
                  value={newWatchTicker}
                  onChange={(event) => setNewWatchTicker(event.target.value.toUpperCase())}
                  placeholder="MSFT"
                />
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={newWatchIsDual}
                  onChange={(event) => setNewWatchIsDual(event.target.checked)}
                />
                <span>Dual listed</span>
              </label>
              <label>
                Ticker US (opcional)
                <input
                  value={newWatchUsTicker}
                  onChange={(event) => setNewWatchUsTicker(event.target.value.toUpperCase())}
                  placeholder="MSFT"
                  disabled={!newWatchIsDual}
                />
              </label>
              <button type="submit" disabled={watchlistBusy}>Adicionar</button>
            </form>
            <div className="watch-items">
              {watchlistLoading && <p className="muted">Carregando watchlist...</p>}
              {!watchlistLoading && watchlist.length === 0 && <p className="muted">Sem tickers cadastrados.</p>}
              {watchlist.map((item) => (
                <article key={item.ticker} className="watch-card">
                  <div className="watch-main">
                    <button
                      type="button"
                      className="watch-ticker"
                      onClick={async () => {
                        setTicker(item.ticker)
                        await loadAll(item.ticker, days, sourceFilter)
                      }}
                    >
                      {item.ticker}
                    </button>
                    {item.is_dual && item.us_ticker && <span className="muted">US: {item.us_ticker}</span>}
                  </div>
                  <button
                    type="button"
                    className="btn-ghost"
                    onClick={() => void onRemoveWatchlist(item.ticker)}
                    disabled={watchlistBusy}
                  >
                    Remover
                  </button>
                </article>
              ))}
            </div>
          </section>

          <section className="panel">
            <h2>Sentimento</h2>
            {panelLoading.summary && <p className="muted">Atualizando sentimento...</p>}
            <div className="chips">
              {sentimentRows.map(([label, value]) => (
                <span key={label} className="chip">
                  {label}: {value}
                </span>
              ))}
            </div>
          </section>

          <section className="panel">
            <h2>Visualizacoes por periodo ({days} dias)</h2>
            {(panelLoading.summary || panelLoading.feed) && <p className="muted">Atualizando visualizacoes...</p>}
            <div className="period-grid">
              <article className="period-card">
                <h3>Sentimento diario</h3>
                {sentimentTimelineRows.length === 0 && <p className="muted">Sem dados para montar a serie.</p>}
                <div className="timeline-list">
                  {sentimentTimelineRows.map((row) => (
                    <div key={row.date} className="timeline-row">
                      <span className="muted">{formatDay(row.date)}</span>
                      <div className="timeline-bar" title={`${row.total} artigos`}>
                        <span
                          className="seg-positive"
                          style={{ width: `${(row.positive / Math.max(row.total, 1)) * 100}%` }}
                        />
                        <span
                          className="seg-neutral"
                          style={{ width: `${(row.neutral / Math.max(row.total, 1)) * 100}%` }}
                        />
                        <span
                          className="seg-negative"
                          style={{ width: `${(row.negative / Math.max(row.total, 1)) * 100}%` }}
                        />
                      </div>
                      <strong>{row.total}</strong>
                    </div>
                  ))}
                </div>
              </article>
              <article className="period-card">
                <h3>Eventos no periodo</h3>
                {eventPeriodRows.length === 0 && <p className="muted">Sem eventos classificados no periodo.</p>}
                <div className="event-list">
                  {eventPeriodRows.map(([event, count]) => (
                    <div key={event} className="event-row">
                      <span className="event-label">{event}</span>
                      <div className="event-bar">
                        <span style={{ width: `${(count / maxEventCount) * 100}%` }} />
                      </div>
                      <strong>{count}</strong>
                    </div>
                  ))}
                </div>
              </article>
            </div>
            <p className="muted">
              Legenda sentimento: verde = positivo, cinza = neutro, vermelho = negativo.
            </p>
          </section>

          <section className="panel">
            <h2>Tendencias sociais por fonte</h2>
            {panelLoading.socialSummary && <p className="muted">Atualizando tendencias sociais...</p>}
            <div className="trend-grid">
              {socialTrendRows.length === 0 && <p className="muted">Sem dados sociais no periodo selecionado.</p>}
              {socialTrendRows.map(([source, count]) => {
                const pct = socialSummary?.total_social_articles
                  ? Math.round((count / socialSummary.total_social_articles) * 100)
                  : 0
                return (
                  <article key={source} className="trend-card">
                    <div className="row">
                      <h3>{source}</h3>
                      <strong>{count}</strong>
                    </div>
                    <p className="muted">{pct}% do volume social</p>
                    <div className="trend-bar">
                      <span style={{ width: `${Math.max(pct, 3)}%` }} />
                    </div>
                  </article>
                )
              })}
            </div>
          </section>

          <section className="panel">
            <h2>Fontes Sociais: Gratuitas vs Credenciais</h2>
            {panelLoading.socialSources && <p className="muted">Atualizando status de fontes...</p>}
            <div className="social-grid">
              {socialSources.map((source) => (
                <article key={source.source} className="social-card">
                  <div className="row">
                    <h3>{source.source}</h3>
                    <span className={source.enabled ? 'status enabled' : 'status disabled'}>
                      {source.enabled ? 'ativo' : 'pendente'}
                    </span>
                  </div>
                  <p>
                    <strong>Acesso:</strong> {source.access_mode}
                  </p>
                  <p>
                    <strong>Seguranca:</strong> {source.security_notes}
                  </p>
                  <p>
                    <strong>Compliance:</strong> {source.compliance_notes}
                  </p>
                </article>
              ))}
            </div>
          </section>

          <section className="panel">
            <h2>Feed ({articles.length})</h2>
            <p className="muted">Filtro atual: {sourceFilter ? sourceTypeLabel(sourceFilter) : 'Todas as fontes'}</p>
            {panelLoading.feed && <p className="muted">Atualizando feed...</p>}
            <div className="feed-toolbar">
              <label>
                Ordenar por
                <select value={feedSort} onChange={(event) => setFeedSort(event.target.value as FeedSort)}>
                  <option value="published_desc">Mais recentes</option>
                  <option value="published_asc">Mais antigos</option>
                  <option value="source_asc">Fonte (A-Z)</option>
                  <option value="title_asc">Titulo (A-Z)</option>
                </select>
              </label>
              <div className="pager">
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => setCurrentPage((page) => Math.max(page - 1, 1))}
                  disabled={currentPage <= 1}
                >
                  Anterior
                </button>
                <span className="muted">
                  Pagina {currentPage} de {totalPages}
                </span>
                <button
                  type="button"
                  className="btn-ghost"
                  onClick={() => setCurrentPage((page) => Math.min(page + 1, totalPages))}
                  disabled={currentPage >= totalPages}
                >
                  Proxima
                </button>
              </div>
            </div>
            <div className="article-list">
              {pagedArticles.map((article) => (
                <article key={article.id} className="article-row">
                  <div className="row">
                    <span className={`badge ${sourceTypeBadge(article.source_type)}`}>{article.source_type}</span>
                    <span className="muted">{article.source}</span>
                    <span className="muted">{formatDate(article.published_at)}</span>
                  </div>
                  <a href={article.url} target="_blank" rel="noreferrer" className="title-link">
                    {article.title}
                  </a>
                </article>
              ))}
            </div>
          </section>
        </>
      )}

      {isIdentityDialogOpen && (
        <section className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="identity-title">
          <div className="dialog-card">
            <h2 id="identity-title">Identidade para login em portais</h2>
            <p className="muted">
              Use este campo para lembrar o Gmail/alias de pesquisa. Nao informe senha, token, cookie ou codigo MFA.
            </p>
            <label>
              Gmail ou alias de pesquisa
              <input
                type="email"
                placeholder="pesquisa+finance@provedor.com"
                value={loginEmail}
                onChange={(event) => setLoginEmail(event.target.value)}
              />
            </label>
            <p className="muted">
              Recomendacao: usar um alias dedicado por plataforma para reduzir risco de reutilizacao de credenciais.
            </p>
            <div className="dialog-actions">
              <button type="button" onClick={saveIdentityEmail}>
                Salvar localmente
              </button>
              <button type="button" className="btn-ghost" onClick={() => setIsIdentityDialogOpen(false)}>
                Fechar
              </button>
              <button
                type="button"
                className="btn-danger"
                onClick={() => {
                  setLoginEmail('')
                  window.localStorage.removeItem('cim_research_login_email')
                }}
              >
                Limpar email salvo
              </button>
            </div>
          </div>
        </section>
      )}
    </main>
  )
}
