import { useEffect, useState } from 'react'
import { chat, demoMode, money } from './chat'
import type { OrderSummary } from './chat'

const statusLabels: Record<string, string> = { recebido: 'Recebido', confirmado: 'Confirmado', cancelado: 'Cancelado', simulado: 'Simulado' }

export default function OrdersPanel({ refreshKey, onUpdate }: { refreshKey?: string; onUpdate: (orders: OrderSummary[]) => void }) {
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [updated, setUpdated] = useState('')
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    let stopped = false
    let running = false
    let timer: ReturnType<typeof setTimeout>
    async function load() {
      if (running || stopped) return
      running = true
      if (document.visibilityState !== 'hidden') {
        try {
          const history = await chat.orders()
          if (stopped) return
          setOrders(history.pedidos)
          onUpdate(history.pedidos)
          setError('')
          setUpdated(new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }))
        } catch (cause) {
          if (!stopped) setError(cause instanceof Error ? cause.message : 'Não foi possível atualizar os pedidos.')
        } finally { if (!stopped) setBusy(false) }
      }
      running = false
      if (!stopped) timer = setTimeout(() => void load(), 10000)
    }
    function visible() { if (document.visibilityState === 'visible') { clearTimeout(timer); void load() } }
    setBusy(true)
    void load()
    document.addEventListener('visibilitychange', visible)
    return () => { stopped = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visible) }
  }, [refreshKey, revision, onUpdate])

  return <section className="history-panel" aria-label="Meus pedidos" aria-busy={busy}>
    <div className="history-heading"><div><p className="eyebrow">ACOMPANHE POR AQUI</p><h2>Meus pedidos</h2></div><button className="text-button" disabled={busy} onClick={() => setRevision(value => value + 1)} aria-label="Atualizar pedidos">↻ Atualizar</button></div>
    <p className="order-help">{demoMode ? 'Pedidos simulados neste navegador.' : 'Pedidos feitos neste navegador, entre suas conversas.'}</p>
    {busy && !orders.length && <p className="order-help" role="status">Buscando seus pedidos…</p>}
    {error && <p className="error" role="alert">{error}{orders.length > 0 && ' Mostrando a última atualização disponível.'}</p>}
    {!busy && !error && !orders.length && <p className="order-help">Você ainda não tem pedidos registrados nesta sessão.</p>}
    <ul className="history-list" aria-live="polite">{orders.map(order => <li key={order.pedido_id}><div><strong>Pedido #{order.pedido_id}</strong><span className={`order-badge status-${order.status}`}>{statusLabels[order.status] || order.status}</span></div><span>{money(order.total)}</span></li>)}</ul>
    {updated && <p className="history-updated">Atualizado às {updated} · atualização automática</p>}
  </section>
}
