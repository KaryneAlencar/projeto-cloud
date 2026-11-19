import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ApiError, chat, demoMode } from './chat'
import type { Conversation, OrderSummary } from './chat'
import MessageContent from './MessageContent'
import OrdersPanel from './OrdersPanel'
import PurchaseSummary from './PurchaseSummary'
import './App.css'

const suggestions = ['Ver o cardápio', 'Quero 2 brownies', 'Como funciona a entrega?']

export default function App() {
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const lock = useRef(false)
  const pending = useRef<{ content: string; id: string } | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)
  const refocus = useRef(false)

  async function run(operation: () => Promise<Conversation>) {
    if (lock.current) return
    lock.current = true
    setBusy(true)
    setError('')
    try {
      const c = await operation()
      setConversation(c)
      try {
        localStorage.setItem(chat.storageKey, c.id)
      } catch {
        setNotice('Não foi possível salvar a conversa neste dispositivo.')
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Não foi possível conectar. Tente novamente.')
    } finally {
      lock.current = false
      setBusy(false)
    }
  }

  function restore() {
    void run(async () => {
      let id: string | null = null
      try { id = localStorage.getItem(chat.storageKey) } catch { /* Storage may be unavailable. */ }
      if (!id) return chat.create()
      try {
        return await chat.get(id)
      } catch (cause) {
        if (!(cause instanceof ApiError) || cause.status !== 404) throw cause
        try { localStorage.setItem(`${chat.storageKey}:previous`, id) } catch { /* Keep history in database. */ }
        setNotice('Iniciamos uma nova conversa. A anterior não está disponível nesta sessão.')
        return chat.create()
      }
    })
  }

  useEffect(() => { restore() }, [])

  // Rola só quando chegam mensagens ou muda o indicador de espera. A sincronização do
  // painel de pedidos troca o objeto da conversa sem trocar a lista de mensagens.
  const messages = conversation?.mensagens
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [messages, busy])

  // O campo fica desabilitado durante o envio e perde o foco; devolve ao terminar.
  useEffect(() => {
    if (busy || !refocus.current) return
    refocus.current = false
    input.current?.focus()
  }, [busy])

  async function send(content: string) {
    if (!conversation || busy || !content.trim()) return
    if (!pending.current || pending.current.content !== content.trim()) {
      pending.current = { content: content.trim(), id: crypto.randomUUID() }
    }
    const payload = pending.current
    await run(async () => {
      const c = await chat.send(conversation.id, payload.content, payload.id)
      pending.current = null
      // Uma sugestão enviada por botão não deve apagar um rascunho diferente no campo.
      setText(current => (current.trim() === payload.content ? '' : current))
      return c
    })
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    refocus.current = !!conversation && !busy && !!text.trim()
    void send(text)
  }

  function startOver() {
    if (!window.confirm('Começar outra conversa? O resumo atual será deixado para trás.')) return
    pending.current = null
    setText('')
    void run(() => chat.create())
  }

  const syncOrders = useCallback((orders: OrderSummary[]) => {
    setConversation(current => {
      const purchase = current?.compra
      if (!current || !purchase?.pedido_id) return current
      const order = orders.find(item => String(item.pedido_id) === String(purchase.pedido_id))
      if (!order || (purchase.pedido_status === order.status && purchase.total === order.total)) return current
      return { ...current, compra: { ...purchase, pedido_status: order.status, total: order.total } }
    })
  }, [])

  const purchase = conversation?.compra

  async function confirmPurchase() {
    if (!conversation || !purchase) return
    await run(async () => {
      try {
        return await chat.confirm(conversation.id, purchase.id)
      } catch (cause) {
        try { setConversation(await chat.get(conversation.id)) } catch { /* Preserve last known state. */ }
        throw cause
      }
    })
  }

  return <div className="app-shell">
    <header className="topbar">
      <a className="brand" href="/" aria-label="Insper Eats, início">
        <span className="brand-mark">ie↗</span>
        <span>
          insper<span className="brand-light">eats</span>
          <small>SEU INTERVALO, MAIS GOSTOSO.</small>
        </span>
      </a>
      <span className="campus">● Campus Insper · São Paulo</span>
      <span className="mode">{demoMode ? 'Demonstração' : 'Modo integrado'}</span>
    </header>
    <main>
      <section className="intro">
        <div>
          <p className="eyebrow">MENOS FILA. MAIS INTERVALO.</p>
          <h1>Bateu a fome?<br /><span>É só chamar.</span></h1>
          <p>Seu próximo lanche começa com uma conversa.</p>
        </div>
        <div className="intro-art" aria-hidden="true" />
      </section>
      {demoMode && (
        <div className="demo-note">
          <strong>Modo demonstração.</strong> Catálogo e respostas simulados. Nenhuma compra real será registrada.
        </div>
      )}
      <div className="workspace">
        <section className="chat-panel" aria-label="Conversa com o vendedor">
          <div className="chat-heading">
            <div className="assistant-avatar">✳</div>
            <div>
              <h2>Seu assistente de pedidos</h2>
              <p>{demoMode ? 'Experimente o Insper Eats' : 'Converse para escolher seu lanche'}</p>
            </div>
            <button className="text-button" disabled={busy} onClick={startOver}>Nova conversa ↗</button>
          </div>
          <div className="messages" role="log" aria-live="polite" aria-label="Histórico da conversa" aria-busy={busy}>
            {!conversation && !busy && <p className="empty-state">Conecte-se para iniciar sua conversa.</p>}
            {messages?.map(m => (
              <div key={m.id} className={`message-row ${m.papel}`}>
                <div className="message">
                  <span className="message-author">{m.papel === 'assistente' ? 'INSPER EATS' : 'VOCÊ'}</span>
                  {m.papel === 'assistente' ? <MessageContent text={m.conteudo} /> : <p>{m.conteudo}</p>}
                </div>
              </div>
            ))}
            {busy && <p className="typing" role="status">● ● ● <span>Preparando sua resposta…</span></p>}
            <div ref={bottom} />
          </div>
          <div className="chat-footer">
            {notice && <p role="status">{notice}</p>}
            {error && (
              <div className="error" role="alert">
                {error}
                {!conversation && <button disabled={busy} onClick={restore}>Tentar conectar</button>}
              </div>
            )}
            <div className="suggestions">
              {suggestions.map(s => (
                <button key={s} disabled={busy || !conversation} onClick={() => void send(s)}>{s} ↗</button>
              ))}
            </div>
            <form onSubmit={submit}>
              <label className="sr-only" htmlFor="message">Sua mensagem</label>
              <input
                id="message"
                ref={input}
                value={text}
                onChange={e => setText(e.target.value)}
                maxLength={2000}
                placeholder="O que você está com vontade de comer?"
                disabled={busy || !conversation}
                autoComplete="off"
              />
              <button className="send" disabled={busy || !conversation || !text.trim()} aria-label="Enviar mensagem">↑</button>
            </form>
            <p className="footer-hint">Você confere os detalhes antes de confirmar qualquer pedido.</p>
          </div>
        </section>
        <div className="orders-column">
          <PurchaseSummary
            purchase={purchase}
            busy={busy}
            confirmationEnabled={conversation?.confirmacao_habilitada !== false}
            onConfirm={() => void confirmPurchase()}
          />
          <OrdersPanel refreshKey={purchase?.pedido_id} onUpdate={syncOrders} />
        </div>
      </div>
      <footer className="page-footer">
        <span>insper eats ✳</span>
        <p>Uma conversa. Um lanche. Um intervalo melhor.</p>
      </footer>
    </main>
  </div>
}
