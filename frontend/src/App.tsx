import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { chat, demoMode, explain, isBusy, isMissingConversation, newId, sleep } from './chat'
import type { Conversation, OrderSummary } from './chat'
import MessageContent from './MessageContent'
import OrdersPanel from './OrdersPanel'
import PurchaseSummary from './PurchaseSummary'
import './App.css'

const suggestions = ['Ver o cardápio', 'Quero 2 brownies', 'Como funciona a entrega?']

// O que a interface está fazendo agora. Só uma operação por vez nesta aba.
type Activity = 'connect' | 'send' | 'confirm' | 'reset' | null
// Mensagem do usuário ainda não confirmada pelo servidor (renderização otimista).
type Outgoing = { id: string; content: string; failure?: string }

const SLOW_AFTER_MS = 8000
const VERY_SLOW_AFTER_MS = 30000
const BUSY_RETRY_MS = 2000
const BUSY_RETRIES = 3

const waitingTexts = [
  'Preparando sua resposta…',
  'Ainda preparando sua resposta… isso pode levar alguns segundos.',
  'O assistente está demorando mais que o normal. Continuamos aguardando a resposta.',
]

const SESSION_RENEWED = 'Sua sessão expirou; começamos uma nova conversa.'

function remember(conversationId: string) {
  try {
    localStorage.setItem(chat.storageKey, conversationId)
    return true
  } catch {
    return false
  }
}

function prefersReducedMotion() {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

// Envia a mensagem; se a conversa ainda estiver ocupada com a anterior (409), repete o
// mesmo mensagem_id algumas vezes antes de desistir. O servidor é idempotente por esse id.
async function sendWithRetry(conversationId: string, message: Outgoing) {
  for (let attempt = 0; ; attempt++) {
    try {
      return await chat.send(conversationId, message.content, message.id)
    } catch (cause) {
      if (!isBusy(cause) || attempt >= BUSY_RETRIES) throw cause
      await sleep(BUSY_RETRY_MS)
    }
  }
}

export default function App() {
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [text, setText] = useState('')
  const [activity, setActivity] = useState<Activity>(null)
  const [outgoing, setOutgoing] = useState<Outgoing | null>(null)
  const [waitLevel, setWaitLevel] = useState(0)
  const [connectError, setConnectError] = useState('')
  const [error, setError] = useState('')
  const [confirmError, setConfirmError] = useState('')
  const [notice, setNotice] = useState('')
  const [announcement, setAnnouncement] = useState('')
  const [highlightedOrder, setHighlightedOrder] = useState('')
  const lock = useRef(false)
  const log = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLInputElement>(null)

  const busy = activity !== null
  const sending = activity === 'send'
  const ready = !!conversation

  function begin(kind: Exclude<Activity, null>) {
    if (lock.current) return false
    lock.current = true
    setActivity(kind)
    return true
  }

  function end() {
    lock.current = false
    setActivity(null)
  }

  function adopt(c: Conversation) {
    setConversation(c)
    if (!remember(c.id)) setNotice('Não foi possível salvar a conversa neste dispositivo.')
  }

  async function openConversation() {
    let id: string | null = null
    try { id = localStorage.getItem(chat.storageKey) } catch { /* Storage may be unavailable. */ }
    if (!id) return chat.create()
    try {
      return await chat.get(id)
    } catch (cause) {
      if (!isMissingConversation(cause)) throw cause
      try { localStorage.setItem(`${chat.storageKey}:previous`, id) } catch { /* Keep history in database. */ }
      setNotice('Iniciamos uma nova conversa. A anterior não está disponível nesta sessão.')
      return chat.create()
    }
  }

  async function connect() {
    if (!begin('connect')) return
    setConnectError('')
    try {
      adopt(await openConversation())
    } catch (cause) {
      setConnectError(explain(cause))
    } finally {
      end()
    }
  }

  // Primeira conexão. A trava impede a repetição do efeito em desenvolvimento (StrictMode).
  useEffect(() => { void connect() }, [])

  // A conversa deixou de existir para esta sessão (por exemplo, a sessão expirou e foi
  // renovada). Começa outra sem prender o usuário e devolve o texto ao campo.
  async function startFresh(draft = '') {
    try {
      adopt(await chat.create())
    } catch {
      return false
    }
    setOutgoing(null)
    setError('')
    setConfirmError('')
    if (draft) setText(current => (current.trim() ? current : draft))
    setNotice(SESSION_RENEWED)
    return true
  }

  async function deliver(message: Outgoing) {
    if (!conversation || !begin('send')) return
    setOutgoing({ id: message.id, content: message.content })
    setError('')
    try {
      const c = await sendWithRetry(conversation.id, message)
      // O estado do servidor já contém a mensagem: sai a cópia otimista, sem duplicar.
      adopt(c)
      setOutgoing(null)
      const last = c.mensagens[c.mensagens.length - 1]
      if (last?.papel === 'assistente') setAnnouncement(`Insper Eats respondeu: ${last.conteudo}`)
    } catch (cause) {
      if (isMissingConversation(cause) && await startFresh(message.content)) return
      setOutgoing({ id: message.id, content: message.content, failure: explain(cause) })
    } finally {
      end()
    }
  }

  function send(content: string) {
    const trimmed = content.trim()
    if (!conversation || lock.current || !trimmed) return
    // Uma sugestão enviada por botão não deve apagar um rascunho diferente no campo.
    setText(current => (current.trim() === trimmed ? '' : current))
    void deliver({ id: newId(), content: trimmed })
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    send(text)
    input.current?.focus()
  }

  function retry() {
    if (outgoing?.failure) void deliver(outgoing)
  }

  // Desiste do envio que falhou e devolve o texto ao campo, se ele estiver vazio.
  function discard() {
    if (!outgoing?.failure) return
    const content = outgoing.content
    setOutgoing(null)
    setText(current => (current.trim() ? current : content))
    input.current?.focus()
  }

  async function startOver() {
    if (!window.confirm('Começar outra conversa? O resumo atual será deixado para trás.')) return
    if (!begin('reset')) return
    setError('')
    try {
      adopt(await chat.create())
      setOutgoing(null)
      setText('')
      setConfirmError('')
      setNotice('')
    } catch (cause) {
      setError(`Não foi possível começar outra conversa. ${explain(cause)}`)
    } finally {
      end()
    }
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
    if (!conversation || !purchase || !begin('confirm')) return
    setConfirmError('')
    try {
      const c = await chat.confirm(conversation.id, purchase.id)
      adopt(c)
      if (c.compra?.pedido_id) {
        setHighlightedOrder(c.compra.pedido_id)
        setAnnouncement(`Pedido ${c.compra.pedido_id} registrado.`)
      }
    } catch (cause) {
      if (isMissingConversation(cause) && await startFresh()) return
      try { setConversation(await chat.get(conversation.id)) } catch { /* Preserve last known state. */ }
      setConfirmError(explain(cause))
    } finally {
      end()
    }
  }

  // Indicador de espera: o texto muda com o tempo para deixar claro que não travou.
  useEffect(() => {
    if (!sending) return
    const slow = setTimeout(() => setWaitLevel(1), SLOW_AFTER_MS)
    const verySlow = setTimeout(() => setWaitLevel(2), VERY_SLOW_AFTER_MS)
    return () => {
      clearTimeout(slow)
      clearTimeout(verySlow)
      setWaitLevel(0)
    }
  }, [sending])

  // Rola só a área de mensagens (nunca a página) quando chega algo novo. A sincronização
  // do painel de pedidos troca o objeto da conversa sem trocar a lista de mensagens.
  const messages = conversation?.mensagens
  useEffect(() => {
    const area = log.current
    if (!area) return
    area.scrollTo({ top: area.scrollHeight, behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  }, [messages, outgoing, sending, waitLevel])

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
            <div className="assistant-avatar" aria-hidden="true">✳</div>
            <div>
              <h2>Seu assistente de pedidos</h2>
              <p>{demoMode ? 'Experimente o Insper Eats' : 'Converse para escolher seu lanche'}</p>
            </div>
            <button className="text-button" disabled={busy || !ready} onClick={() => void startOver()}>
              Nova conversa ↗
            </button>
          </div>
          {/* A leitura por voz usa a região discreta abaixo: só a resposta nova é anunciada. */}
          <div
            className="messages"
            ref={log}
            role="log"
            aria-live="off"
            aria-label="Histórico da conversa"
            tabIndex={0}
          >
            {!ready && !connectError && (
              <p className="empty-state connecting" role="status">
                <span className="dots" aria-hidden="true"><i /><i /><i /></span>
                Conectando…
              </p>
            )}
            {!ready && connectError && (
              <div className="empty-state">
                <div className="error" role="alert">
                  <p>Não foi possível conectar. {connectError}</p>
                  <button onClick={() => void connect()}>Tentar conectar</button>
                </div>
              </div>
            )}
            {messages?.map(m => (
              <div key={m.id} className={`message-row ${m.papel}`}>
                <div className="message">
                  <span className="message-author">{m.papel === 'assistente' ? 'INSPER EATS' : 'VOCÊ'}</span>
                  {m.papel === 'assistente' ? <MessageContent text={m.conteudo} /> : <p>{m.conteudo}</p>}
                </div>
              </div>
            ))}
            {ready && outgoing && (
              <div className={`message-row usuario ${outgoing.failure ? 'failed' : 'pending'}`}>
                <div className="message">
                  <span className="message-author">VOCÊ</span>
                  <p>{outgoing.content}</p>
                </div>
                {outgoing.failure && (
                  <div className="send-failure" role="alert">
                    <p><strong>Não enviada.</strong> {outgoing.failure}</p>
                    <div className="send-failure-actions">
                      <button className="retry" onClick={retry}>Tentar de novo</button>
                      <button className="link-button" onClick={discard}>Descartar</button>
                    </div>
                  </div>
                )}
              </div>
            )}
            {sending && (
              <p className="typing" role="status">
                <span className="dots" aria-hidden="true"><i /><i /><i /></span>
                <span>{waitingTexts[waitLevel]}</span>
              </p>
            )}
          </div>
          <p className="sr-only" role="status" aria-live="polite">{announcement}</p>
          <div className="chat-footer">
            {notice && <p className="notice" role="status">{notice}</p>}
            {error && <p className="error" role="alert">{error}</p>}
            <div className="suggestions">
              {suggestions.map(s => (
                <button
                  key={s}
                  type="button"
                  aria-disabled={busy || !ready}
                  onClick={() => send(s)}
                >
                  {s} ↗
                </button>
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
                placeholder={ready ? 'O que você está com vontade de comer?' : 'Conectando…'}
                disabled={!ready}
                autoComplete="off"
                enterKeyHint="send"
              />
              <button
                className="send"
                disabled={busy || !ready || !text.trim()}
                aria-label={sending ? 'Enviando mensagem' : 'Enviar mensagem'}
              >
                <span aria-hidden="true">↑</span>
              </button>
            </form>
            <p className="footer-hint">Você confere os detalhes antes de confirmar qualquer pedido.</p>
          </div>
        </section>
        <div className="orders-column">
          <PurchaseSummary
            purchase={purchase}
            busy={busy}
            confirming={activity === 'confirm'}
            error={confirmError}
            highlightedOrder={highlightedOrder}
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
