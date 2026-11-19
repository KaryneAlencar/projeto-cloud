import { demoMode, money } from './chat'
import type { Purchase } from './chat'

type Props = {
  purchase: Purchase | null | undefined
  busy: boolean
  // false somente quando o servidor informa que a confirmação está desligada.
  confirmationEnabled: boolean
  onConfirm: () => void
}

function statusLabel(purchase: Purchase) {
  if (purchase.status === 'confirmado') return demoMode ? 'Compra simulada' : 'Pedido registrado'
  if (purchase.status === 'confirmando') return 'Confirmação pendente de recuperação'
  return 'Aguardando sua confirmação'
}

function confirmLabel(purchase: Purchase) {
  if (demoMode) return 'Simular confirmação'
  return purchase.status === 'confirmando' ? 'Repetir confirmação' : 'Confirmar pedido'
}

function helpText(purchase: Purchase, confirmationEnabled: boolean) {
  if (!confirmationEnabled) return 'A confirmação está indisponível.'
  if (purchase.status === 'confirmando') {
    return 'Repita para recuperar o mesmo pedido. A seleção fica congelada até resolver esta tentativa.'
  }
  if (!purchase.cliente || !purchase.local_entrega) return 'Informe nome e local de entrega na conversa.'
  return 'Quer mudar algo? Peça na conversa antes de confirmar.'
}

function PurchaseDetails({ purchase, busy, confirmationEnabled, onConfirm }: Props & { purchase: Purchase }) {
  const open = purchase.status === 'preparando' || purchase.status === 'confirmando'
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
        className="confirm"
        disabled={busy || !purchase.cliente || !purchase.local_entrega || !confirmationEnabled}
        onClick={onConfirm}
      >
        {confirmLabel(purchase)} →
      </button>
      <p className="order-help">{helpText(purchase, confirmationEnabled)}</p>
    </>}
    {purchase.pedido_id && (
      <p className="receipt" role="status">#{purchase.pedido_id} · {purchase.pedido_status || 'recebido'}</p>
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
