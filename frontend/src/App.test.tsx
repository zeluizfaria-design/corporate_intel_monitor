import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  } as Response
}

function createArticles(total: number) {
  return Array.from({ length: total }).map((_, index) => ({
    id: `article-${index}`,
    source: index % 2 === 0 ? 'newswire' : 'forum',
    source_type: index % 2 === 0 ? 'news' : 'social',
    url: `https://example.com/${index}`,
    title: `Noticia ${index}`,
    content: 'conteudo',
    published_at: `2026-03-${String((index % 28) + 1).padStart(2, '0')}T10:00:00Z`,
    sentiment_label: index % 3 === 0 ? 'POSITIVE' : index % 3 === 1 ? 'NEGATIVE' : 'NEUTRAL',
    event_type: index % 2 === 0 ? 'earnings' : 'guidance',
  }))
}

describe('App', () => {
  let watchlistItems: Array<{ ticker: string; is_dual: boolean; us_ticker?: string | null }>
  let fetchMock: any
  let failSocialSources: boolean
  let failWatchlistPost: boolean
  let failWatchlistDelete: boolean
  let collectionStatuses: Array<'queued' | 'running' | 'completed' | 'failed'>
  let collectionErrorMessage: string | null
  let collectionSummary: Record<string, unknown> | null
  let failCollectionStatus: boolean

  beforeEach(() => {
    watchlistItems = []
    failSocialSources = false
    failWatchlistPost = false
    failWatchlistDelete = false
    collectionStatuses = ['completed']
    collectionErrorMessage = null
    collectionSummary = { total_articles: 5, collector_failures: [] }
    failCollectionStatus = false
    vi.spyOn(window, 'open').mockImplementation(() => null)
    fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      const method = init?.method ?? 'GET'

      if (url.includes('/articles/NVDA/summary')) {
        return jsonResponse({
          ticker: 'NVDA',
          days: 7,
          total_articles: 25,
          sentiment: { POSITIVE: 10, NEGATIVE: 8, NEUTRAL: 7 },
          avg_sentiment_compound: 0.12,
          event_types: { earnings: 12, guidance: 8, merger: 2 },
          sources: { newswire: 14, forum: 11 },
        })
      }

      if (url.includes('/articles/NVDA?')) {
        return jsonResponse(createArticles(25))
      }

      if (url.includes('/articles/MSFT?')) {
        return jsonResponse(createArticles(3))
      }

      if (url.includes('/articles/MSFT/summary')) {
        return jsonResponse({
          ticker: 'MSFT',
          days: 7,
          total_articles: 3,
          sentiment: { POSITIVE: 1, NEGATIVE: 1, NEUTRAL: 1 },
          avg_sentiment_compound: 0.01,
          event_types: { earnings: 2, guidance: 1 },
          sources: { newswire: 2, forum: 1 },
        })
      }

      if (url.includes('/social/sources')) {
        if (failSocialSources) {
          return {
            ok: false,
            status: 500,
            statusText: 'Internal Server Error',
            json: async () => ({ detail: 'falha forçada' }),
            text: async () => 'falha forçada',
          } as Response
        }

        return jsonResponse([
          {
            source: 'reddit',
            access_mode: 'public_api',
            configured: true,
            enabled: true,
            security_notes: 'ok',
            compliance_notes: 'ok',
          },
        ])
      }

      if (url.includes('/social/NVDA/summary')) {
        return jsonResponse({
          ticker: 'NVDA',
          days: 7,
          total_social_articles: 11,
          sources: { reddit: 6, stocktwits: 5 },
          public_sources: ['reddit'],
        })
      }

      if (url.includes('/social/MSFT/summary')) {
        return jsonResponse({
          ticker: 'MSFT',
          days: 7,
          total_social_articles: 2,
          sources: { reddit: 2 },
          public_sources: ['reddit'],
        })
      }

      if (url.endsWith('/watchlist') && method === 'GET') {
        return jsonResponse(watchlistItems)
      }

      if (url.endsWith('/watchlist') && method === 'POST') {
        if (failWatchlistPost) {
          return {
            ok: false,
            status: 500,
            statusText: 'Internal Server Error',
            json: async () => ({ detail: 'erro ao inserir watchlist' }),
            text: async () => 'erro ao inserir watchlist',
          } as Response
        }

        const body = JSON.parse(String(init?.body ?? '{}')) as {
          ticker?: string
          is_dual?: boolean
          us_ticker?: string | null
        }
        const ticker = (body.ticker ?? '').trim().toUpperCase()
        if (!ticker) {
          return {
            ok: false,
            status: 400,
            statusText: 'Bad Request',
            json: async () => ({ detail: 'ticker required' }),
            text: async () => 'ticker required',
          } as Response
        }
        watchlistItems.push({
          ticker,
          is_dual: Boolean(body.is_dual),
          us_ticker: body.us_ticker ?? null,
        })
        return jsonResponse({ ok: true })
      }

      if (url.includes('/watchlist/') && method === 'DELETE') {
        if (failWatchlistDelete) {
          return {
            ok: false,
            status: 500,
            statusText: 'Internal Server Error',
            json: async () => ({ detail: 'erro ao remover watchlist' }),
            text: async () => 'erro ao remover watchlist',
          } as Response
        }

        const ticker = decodeURIComponent(url.split('/watchlist/')[1] || '').toUpperCase()
        watchlistItems = watchlistItems.filter((item) => item.ticker !== ticker)
        return jsonResponse({ ok: true })
      }

      if (url.endsWith('/collect') && method === 'POST') {
        return jsonResponse({
          status: 'started',
          job_id: 'job-nvda-001',
          ticker: 'NVDA',
          days_back: 30,
        })
      }

      if (url.includes('/collect/job-nvda-001') && method === 'GET') {
        if (failCollectionStatus) {
          return {
            ok: false,
            status: 404,
            statusText: 'Not Found',
            json: async () => ({ detail: 'Collection job job-nvda-001 not found' }),
            text: async () => 'Collection job job-nvda-001 not found',
          } as Response
        }

        const next = collectionStatuses.shift() ?? 'completed'
        return jsonResponse({
          job_id: 'job-nvda-001',
          status: next,
          ticker: 'NVDA',
          days_back: 30,
          queued_at: '2026-03-06T00:00:00Z',
          started_at: next === 'queued' ? null : '2026-03-06T00:00:01Z',
          finished_at: next === 'completed' || next === 'failed' ? '2026-03-06T00:00:02Z' : null,
          error: next === 'failed' ? (collectionErrorMessage ?? 'erro na coleta') : null,
          summary: next === 'completed' ? collectionSummary : null,
        })
      }

      return {
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: async () => ({}),
        text: async () => 'Not Found',
      } as Response
    })
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('carrega dashboard e permite paginar o feed', async () => {
    render(<App />)

    expect(await screen.findByText('Feed (25)')).toBeInTheDocument()
    expect(screen.getByText('Pagina 1 de 2')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Proxima' }))

    await waitFor(() => {
      expect(screen.getByText('Pagina 2 de 2')).toBeInTheDocument()
    })
  })

  it('aplica filtro de fonte no feed ao consultar', async () => {
    render(<App />)
    expect(await screen.findByText('Feed (25)')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Filtro de fonte'), { target: { value: 'social' } })
    fireEvent.click(screen.getByRole('button', { name: 'Consultar' }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/articles/NVDA?days=7&source_type=social')
    })
    expect(screen.getByText('Filtro atual: Social')).toBeInTheDocument()
  })

  it('permite adicionar ticker na watchlist e consultar por clique', async () => {
    render(<App />)
    expect(await screen.findByText('Watchlist')).toBeInTheDocument()

    const watchTickerInput = screen
      .getAllByPlaceholderText('MSFT')
      .find((element) => !element.hasAttribute('disabled'))
    expect(watchTickerInput).toBeTruthy()

    fireEvent.change(watchTickerInput!, { target: { value: 'MSFT' } })
    fireEvent.click(screen.getByRole('button', { name: 'Adicionar' }))

    const watchTicker = await screen.findByRole('button', { name: 'MSFT' })
    fireEvent.click(watchTicker)

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/articles/MSFT/summary?days=7')
      expect(fetchMock).toHaveBeenCalledWith('/articles/MSFT?days=7')
      expect(fetchMock).toHaveBeenCalledWith('/social/MSFT/summary?days=7')
    })
  })

  it('permite remover ticker da watchlist', async () => {
    render(<App />)
    expect(await screen.findByText('Watchlist')).toBeInTheDocument()

    const watchTickerInput = screen
      .getAllByPlaceholderText('MSFT')
      .find((element) => !element.hasAttribute('disabled'))
    expect(watchTickerInput).toBeTruthy()

    fireEvent.change(watchTickerInput!, { target: { value: 'MSFT' } })
    fireEvent.click(screen.getByRole('button', { name: 'Adicionar' }))
    expect(await screen.findByRole('button', { name: 'MSFT' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Remover' }))

    await waitFor(() => {
      expect(screen.queryByRole('button', { name: 'MSFT' })).not.toBeInTheDocument()
      expect(fetchMock).toHaveBeenCalledWith('/watchlist/MSFT', { method: 'DELETE' })
    })
  })

  it('abre exportacao CSV com ticker e dias atuais', async () => {
    const openSpy = vi.spyOn(window, 'open')
    render(<App />)

    expect(await screen.findByText('Feed (25)')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Exportar CSV' }))

    expect(openSpy).toHaveBeenCalledWith('/export/NVDA?days=7', '_blank')
  })

  it('exibe erro agregado em falha parcial e preserva paineis bem-sucedidos', async () => {
    failSocialSources = true
    render(<App />)

    expect(await screen.findByText(/Erro: Fontes sociais:/)).toBeInTheDocument()
    expect(screen.getByText('Feed (25)')).toBeInTheDocument()
    expect(screen.getByText('Total')).toBeInTheDocument()
  })

  it('exibe erro ao falhar adicao na watchlist', async () => {
    failWatchlistPost = true
    render(<App />)
    expect(await screen.findByText('Watchlist')).toBeInTheDocument()

    const watchTickerInput = screen
      .getAllByPlaceholderText('MSFT')
      .find((element) => !element.hasAttribute('disabled'))
    expect(watchTickerInput).toBeTruthy()

    fireEvent.change(watchTickerInput!, { target: { value: 'MSFT' } })
    fireEvent.click(screen.getByRole('button', { name: 'Adicionar' }))

    expect(await screen.findByText(/Erro: 500 Internal Server Error - erro ao inserir watchlist/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'MSFT' })).not.toBeInTheDocument()
  })

  it('exibe erro ao falhar remocao na watchlist e preserva item', async () => {
    render(<App />)
    expect(await screen.findByText('Watchlist')).toBeInTheDocument()

    const watchTickerInput = screen
      .getAllByPlaceholderText('MSFT')
      .find((element) => !element.hasAttribute('disabled'))
    expect(watchTickerInput).toBeTruthy()

    fireEvent.change(watchTickerInput!, { target: { value: 'MSFT' } })
    fireEvent.click(screen.getByRole('button', { name: 'Adicionar' }))
    expect(await screen.findByRole('button', { name: 'MSFT' })).toBeInTheDocument()

    failWatchlistDelete = true
    fireEvent.click(screen.getByRole('button', { name: 'Remover' }))

    expect(await screen.findByText(/Erro: 500 Internal Server Error - erro ao remover watchlist/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'MSFT' })).toBeInTheDocument()
  })

  it('acompanha coleta por job_id ate completar e recarrega os paineis', async () => {
    collectionStatuses = ['queued', 'running', 'completed']
    render(<App />)
    expect(await screen.findByText('Feed (25)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Coletar agora' }))

    await waitFor(() => {
      expect(screen.getByText('Status da coleta')).toBeInTheDocument()
      expect(screen.getByRole('status').textContent).toContain('Job: job-nvda-001')
      expect(screen.getByRole('status').textContent).toContain('Janela coleta: 30 dias')
      expect(screen.getByRole('status').textContent).toContain('concluida')
    })
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/collect', expect.any(Object))
      expect(fetchMock).toHaveBeenCalledWith('/collect/job-nvda-001')
    })
  })

  it('exibe erro quando coleta finaliza com falha', async () => {
    collectionStatuses = ['failed']
    collectionErrorMessage = 'falha no collector x'
    render(<App />)
    expect(await screen.findByText('Feed (25)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Coletar agora' }))

    expect(await screen.findByText(/Erro: Falha ao disparar coleta: falha no collector x/)).toBeInTheDocument()
    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toContain('Job: job-nvda-001')
      expect(screen.getByRole('status').textContent).toContain('falhou')
      expect(screen.getByRole('status').textContent).toContain('falha no collector x')
    })
    expect(screen.getByText('Falha: falha no collector x')).toBeInTheDocument()
  })

  it('exibe erro ao falhar consulta de status da coleta', async () => {
    failCollectionStatus = true
    render(<App />)
    expect(await screen.findByText('Feed (25)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Coletar agora' }))

    expect(
      await screen.findByText(
        /Erro: Falha ao disparar coleta: 404 Not Found - Collection job job-nvda-001 not found/,
      ),
    ).toBeInTheDocument()
  })

  it('exibe erro de timeout quando job permanece em execucao no polling', async () => {
    collectionStatuses = Array.from({ length: 40 }, (): 'running' => 'running')

    render(<App />)
    expect(await screen.findByText('Feed (25)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Coletar agora' }))

    await waitFor(() => {
      expect(
        screen.getByText(/Erro: Falha ao disparar coleta: Timeout ao acompanhar coleta job-nvda-001/),
      ).toBeInTheDocument()
    }, { timeout: 12000 })
    expect(screen.getByRole('status').textContent).toContain('em execucao')
  }, 15000)

  it('permite reconsultar status apos timeout e concluir sem disparar nova coleta', async () => {
    collectionStatuses = [...Array.from({ length: 30 }, (): 'running' => 'running'), 'completed']
    render(<App />)
    expect(await screen.findByText('Feed (25)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Coletar agora' }))

    await waitFor(() => {
      expect(
        screen.getByText(/Erro: Falha ao disparar coleta: Timeout ao acompanhar coleta job-nvda-001/),
      ).toBeInTheDocument()
    }, { timeout: 12000 })

    fireEvent.click(screen.getByRole('button', { name: 'Atualizar status' }))

    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toContain('concluida')
    })
    expect(
      fetchMock.mock.calls.filter((args: [RequestInfo | URL]) => String(args[0]).endsWith('/collect')).length,
    ).toBe(1)
  }, 15000)

  it('exibe aviso de sucesso parcial quando coleta termina com collector_failures', async () => {
    collectionSummary = {
      total_articles: 5,
      collector_failures: [{ collector: 'StockTwitsCollector', error: '403 Forbidden' }],
    }

    render(<App />)
    expect(await screen.findByText('Feed (25)')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Coletar agora' }))

    await waitFor(() => {
      expect(screen.getByRole('status').textContent).toContain(
        'Coleta concluida com falhas parciais em 1 coletor(es).',
      )
    })
  })
})
