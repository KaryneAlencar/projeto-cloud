import { useEffect, useRef } from 'react'
import { demoMode, money, orderStatusLabel } from './chat'
import type { Purchase } from './chat'

type Props = {
  purchase: Purchase | null | undefined
  busy: boolean
  // true enquanto a confirmação desta compra está em andamento.
  confirming: boolean
  // Falha da última tentativa de confirmação, exibida junto do botão.
  error: string
  // pedido_id recém-registrado nesta visita: recebe destaque breve e rolagem no celular.
  highlightedOrder: string
  // false somente quando o servidor informa que a confirmação está desligada.
  confirmationEnabled: boolean
  onConfirm: () => void
}

function statusLabel(purchase: Purchase) {
  if (purchase.status === 'confirmado') return demoMode ? 'Compra simulada' : 'Pedido registrado'
  if (purchase.status === 'confirmando') return 'Confirmação pendente de recuperação'
  return 'Aguardando sua confirmação'
}

function confirmLabel(purchase: Purchase, confirming: boolean) {
  if (confirming) return 'Confirmando…'
  if (demoMode) return 'Simular confirmação →'
  return purchase.status === 'confirmando' ? 'Repetir confirmação →' : 'Confirmar pedido →'
}

function helpText(purchase: Purchase, confirmationEnabled: boolean) {
  if (!confirmationEnabled) return 'A confirmação está indisponível.'
  if (purchase.status === 'confirmando') {
    return 'Repita para recuperar o mesmo pedido. A seleção fica congelada até resolver esta tentativa.'
  }
  if (!purchase.cliente || !purchase.local_entrega) return 'Informe nome e local de entrega na conversa.'
  return 'Quer mudar algo? Peça na conversa antes de confirmar.'
}

function Receipt({ purchase, highlighted }: { purchase: Purchase; highlighted: boolean }) {
  const receipt = useRef<HTMLParagraphElement>(null)
  const status = purchase.pedido_status || 'recebido'

  // Em telas estreitas o resumo fica abaixo do chat: leva o comprovante até a vista.
  useEffect(() => {
    if (!highlighted || !window.matchMedia('(max-width: 700px)').matches) return
    const smooth = !window.matchMedia('(prefers-reduced-motion: reduce)').matches
    receipt.current?.scrollIntoView({ behavior: smooth ? 'smooth' : 'auto', block: 'center' })
  }, [highlighted])

  return (
    <p ref={receipt} className={`receipt${highlighted ? ' receipt-new' : ''}`} role="status">
      <strong>#{purchase.pedido_id}</strong> · <span key={status} className="status-change">
        {orderStatusLabel(status)}
      </span>
    </p>
  )
}

function PurchaseDetails(props: Props & { purchase: Purchase }) {
  const { purchase, busy, confirming, error, highlightedOrder, confirmationEnabled, onConfirm } = props
  const open = purchase.status === 'preparando' || purchase.status === 'confirmando'
  const incomplete = !purchase.cliente || !purchase.local_entrega
  return <>
    <span className="purchase-status">{statusLabel(purchase)}</span>
    <ul className="order-items">
      {purchase.itens.map(p => (
        <li key={p.nome}>
          <span className="quantity">{p.quantidade}×</span>
          <span>{p.nome}</span>
          <strong>{money(p.quantidade * p.preco_unitario)}</strong>
        </li>
      ))}
    </ul>
    <dl className="delivery">
      <dt>Para</dt>
      <dd>{purchase.cliente || 'Informe seu nome no chat'}</dd>
      <dt>Entregar em</dt>
      <dd>{purchase.local_entrega || 'Informe prédio e sala no chat'}</dd>
    </dl>
    <div className="total">
      <span>Total{purchase.status === 'preparando' ? ' estimado' : ''}</span>
      <strong>{money(purchase.total)}</strong>
    </div>
    {open && <>
      <button
        className={`confirm${confirming ? ' working' : ''}`}
        disabled={busy || incomplete || !confirmationEnabled}
        aria-busy={confirming}
        onClick={onConfirm}
      >
        {confirmLabel(purchase, confirming)}
      </button>
      {error && <p className="error confirm-error" role="alert">{error}</p>}
      <p className="order-help">{helpText(purchase, confirmationEnabled)}</p>
    </>}
    {purchase.pedido_id && (
      <Receipt purchase={purchase} highlighted={highlightedOrder === purchase.pedido_id} />
    )}
  </>
}

export default function PurchaseSummary(props: Props) {
  const { purchase } = props
  return <aside className="order-panel">
    <p className="eyebrow">SEU INTERVALO ↗</p>
    <h2>Resumo do pedido</h2>
    {purchase ? <PurchaseDetails {...props} purchase={purchase} /> : (
      <div className="order-empty">
        <div aria-hidden="true">▤</div>
        <h3>Seu lanche vem aí.</h3>
        <p>Escolha o que você quer pelo chat. Os detalhes aparecem aqui.</p>
      </div>
    )}
    <div className="how-it-works">
      <p className="eyebrow">DO SEU JEITO, SEM COMPLICAÇÃO</p>
      <ol>
        <li><span>01</span> Conte o que quer comer</li>
        <li><span>02</span> Informe onde está</li>
        <li><span>03</span> Confira e confirme</li>
      </ol>
    </div>
  </aside>
}
