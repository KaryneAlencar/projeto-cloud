import { useEffect, useRef, useState } from 'react'
import { chat, demoMode, money, orderStatusLabel } from './chat'
import type { OrderSummary } from './chat'

const POLL_MS = 10000
// Logo após um pedido novo, enquanto ele ainda está "recebido", consulta mais vezes
// para mostrar a confirmação do worker sem esperar o ciclo normal.
const FAST_POLL_MS = 3000
const FAST_POLLS = 10

// Texto para leitores de tela: só o que mudou (pedido novo ou troca de status), nunca a
// lista inteira. Na primeira carga (previous nulo) nada é anunciado.
function statusChanges(previous: Map<string, string> | null, list: OrderSummary[]) {
  if (!previous) return ''
  return list
    .filter(order => previous.get(String(order.pedido_id)) !== order.status)
    .map(order => `Pedido ${order.pedido_id}: ${orderStatusLabel(order.status)}.`)
    .join(' ')
}

type Props = { refreshKey?: string; onUpdate: (orders: OrderSummary[]) => void }

export default function OrdersPanel({ refreshKey, onUpdate }: Props) {
  const [orders, setOrders] = useState<OrderSummary[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')
  const [updated, setUpdated] = useState('')
  const [revision, setRevision] = useState(0)
  const [announcement, setAnnouncement] = useState('')
  const known = useRef<Map<string, string> | null>(null)

  useEffect(() => {
    let stopped = false
    let running = false
    let timer: ReturnType<typeof setTimeout>
    let fastPolls = refreshKey ? FAST_POLLS : 0
    let waiting = false
    async function load() {
      if (running || stopped) return
      running = true
      if (document.visibilityState !== 'hidden') {
        try {
          const history = await chat.orders()
          if (stopped) return
          setOrders(history.pedidos)
          waiting = history.pedidos.some(order => order.status === 'recebido')
          onUpdate(history.pedidos)
          const changes = statusChanges(known.current, history.pedidos)
          known.current = new Map(history.pedidos.map(order => [String(order.pedido_id), order.status]))
          if (changes) setAnnouncement(changes)
          setError('')
          setUpdated(new Date().toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' }))
        } catch (cause) {
          if (!stopped) setError(cause instanceof Error ? cause.message : 'Não foi possível atualizar os pedidos.')
        } finally { if (!stopped) setBusy(false) }
      }
      running = false
      if (stopped) return
      const fast = waiting && fastPolls-- > 0
      timer = setTimeout(() => void load(), fast ? FAST_POLL_MS : POLL_MS)
    }
    function visible() { if (document.visibilityState === 'visible') { clearTimeout(timer); void load() } }
    setBusy(true)
    void load()
    document.addEventListener('visibilitychange', visible)
    return () => { stopped = true; clearTimeout(timer); document.removeEventListener('visibilitychange', visible) }
  }, [refreshKey, revision, onUpdate])

  return <section className="history-panel" aria-label="Meus pedidos" aria-busy={busy}>
    <div className="history-heading">
      <div>
        <p className="eyebrow">ACOMPANHE POR AQUI</p>
        <h2>Meus pedidos</h2>
      </div>
      <button
        className="text-button"
        disabled={busy}
        onClick={() => setRevision(value => value + 1)}
        aria-label="Atualizar pedidos"
      >
        ↻ Atualizar
      </button>
    </div>
    <p className="order-help">{demoMode ? 'Pedidos simulados neste navegador.' : 'Pedidos feitos neste navegador, entre suas conversas.'}</p>
    {busy && !orders.length && <p className="order-help" role="status">Buscando seus pedidos…</p>}
    {error && <p className="error" role="alert">{error}{orders.length > 0 && ' Mostrando a última atualização disponível.'}</p>}
    {!busy && !error && !orders.length && <p className="order-help">Você ainda não tem pedidos registrados nesta sessão.</p>}
    <ul className="history-list">
      {orders.map(order => (
        <li key={order.pedido_id}>
          <div>
            <strong>Pedido #{order.pedido_id}</strong>
            {/* A chave troca com o status: o selo novo entra com uma transição discreta. */}
            <span key={order.status} className={`order-badge status-change status-${order.status}`}>
              {orderStatusLabel(order.status)}
            </span>
          </div>
          <span>{money(order.total)}</span>
        </li>
      ))}
    </ul>
    <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
    {updated && <p className="history-updated">Atualizado às {updated} · atualização automática</p>}
  </section>
}
