import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = {
  children: ReactNode
}

type State = {
  hasError: boolean
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false }

  static getDerivedStateFromError(): State {
    return { hasError: true }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI runtime error', error, info)
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="error-state">
          <h1>Falha de renderizacao</h1>
          <p>Atualize a pagina. Se persistir, verifique o console e a API em :8000.</p>
        </main>
      )
    }

    return this.props.children
  }
}
