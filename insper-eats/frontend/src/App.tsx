import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { chat, demoMode, money } from './chat'
import type { Conversation } from './chat'
import './App.css'

export default function App() {
  const [conversation, setConversation] = useState<Conversation | null>(null)
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const lock = useRef(false)
  const pending = useRef<{ content: string; id: string } | null>(null)
  const bottom = useRef<HTMLDivElement>(null)
  async function run(operation: () => Promise<Conversation>) {
    if (lock.current) return
    lock.current = true; setBusy(true); setError('')
    try { const c = await operation(); setConversation(c); try { localStorage.setItem(chat.storageKey, c.id) } catch { setNotice('Não foi possível salvar a conversa neste dispositivo.') } }
    catch (e) { setError(e instanceof Error ? e.message : 'Não foi possível conectar. Tente novamente.') }
    finally { lock.current = false; setBusy(false) }
  }
  function restore() { void run(async () => { let id: string | null = null; try { id = localStorage.getItem(chat.storageKey) } catch { /* Storage may be unavailable. */ } return id ? chat.get(id) : chat.create() }) }
  useEffect(() => { restore() }, [])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth', block: 'end' }) }, [conversation, busy])
  async function send(content: string) {
    if (!conversation || busy || !content.trim()) return
    if (!pending.current || pending.current.content !== content.trim()) pending.current = { content: content.trim(), id: crypto.randomUUID() }
    const payload = pending.current
    await run(async () => { const c = await chat.send(conversation.id, payload.content, payload.id); pending.current = null; setText(''); return c })
  }
  function submit(e: FormEvent) { e.preventDefault(); void send(text) }
  const purchase = conversation?.compra
  return <div className="app-shell">
    <header className="topbar"><a className="brand" href="/" aria-label="Insper Eats, início"><span className="brand-mark">ie↗</span><span>insper<span className="brand-light">eats</span><small>SEU INTERVALO, MAIS GOSTOSO.</small></span></a><span className="campus">● Campus Insper · São Paulo</span><span className="mode">{demoMode ? 'Demonstração' : 'Modo integrado'}</span></header>
    <main><section className="intro"><div><p className="eyebrow">MENOS FILA. MAIS INTERVALO.</p><h1>Bateu a fome?<br /><span>É só chamar.</span></h1><p>Seu próximo lanche começa com uma conversa.</p></div><div className="intro-stamp" aria-hidden="true">feito para<strong>o seu<br />intervalo.</strong><span>✳</span></div></section>
    {demoMode && <div className="demo-note"><strong>Modo demonstração.</strong> Catálogo e respostas simulados. Nenhuma compra real será registrada.</div>}
    <div className="workspace"><section className="chat-panel" aria-label="Conversa com o vendedor"><div className="chat-heading"><div className="assistant-avatar">✳</div><div><h2>Seu assistente de pedidos</h2><p>{demoMode ? 'Experimente o Insper Eats' : 'Converse para escolher seu lanche'}</p></div><button className="text-button" disabled={busy} onClick={() => { if (window.confirm('Começar outra conversa? O resumo atual será deixado para trás.')) { pending.current = null; setText(''); void run(() => chat.create()) } }}>Nova conversa ↗</button></div>
    <div className="messages" role="log" aria-live="polite" aria-label="Histórico da conversa" aria-busy={busy}>{!conversation && !busy && <p className="empty-state">Conecte-se para iniciar sua conversa.</p>}{conversation?.mensagens.map(m => <div key={m.id} className={`message-row ${m.papel}`}><div className="message"><span className="message-author">{m.papel === 'assistente' ? 'INSPER EATS' : 'VOCÊ'}</span><p>{m.conteudo}</p></div></div>)}{busy && <p className="typing" role="status">● ● ● <span>Preparando sua resposta…</span></p>}<div ref={bottom} /></div>
    <div className="chat-footer">{notice && <p role="status">{notice}</p>}{error && <div className="error" role="alert">{error}{!conversation && <button disabled={busy} onClick={restore}>Tentar conectar</button>}</div>}<div className="suggestions">{['Ver o cardápio', 'Quero 2 brownies', 'Como funciona a entrega?'].map(s => <button key={s} disabled={busy || !conversation} onClick={() => void send(s)}>{s} ↗</button>)}</div><form onSubmit={submit}><label className="sr-only" htmlFor="message">Sua mensagem</label><input id="message" value={text} onChange={e => setText(e.target.value)} maxLength={2000} placeholder="O que você está com vontade de comer?" disabled={busy || !conversation} autoComplete="off" /><button className="send" disabled={busy || !conversation || !text.trim()} aria-label="Enviar mensagem">↑</button></form><p className="footer-hint">Você confere os detalhes antes de confirmar qualquer pedido.</p></div></section>
    <aside className="order-panel"><p className="eyebrow">SEU INTERVALO ↗</p><h2>Resumo do pedido</h2>{purchase ? <><span className="purchase-status">{purchase.status === 'confirmado' ? (demoMode ? 'Compra simulada' : 'Pedido registrado') : 'Aguardando sua confirmação'}</span><ul className="order-items">{purchase.itens.map(p => <li key={p.nome}><span className="quantity">{p.quantidade}×</span><span>{p.nome}</span><strong>{money(p.quantidade * p.preco_unitario)}</strong></li>)}</ul><dl className="delivery"><dt>Para</dt><dd>{purchase.cliente || 'Informe seu nome no chat'}</dd><dt>Entregar em</dt><dd>{purchase.local_entrega || 'Informe prédio e sala no chat'}</dd></dl><div className="total"><span>Total{purchase.status === 'preparando' ? ' estimado' : ''}</span><strong>{money(purchase.total)}</strong></div>{purchase.status === 'preparando' && <><button className="confirm" disabled={busy || !purchase.cliente || !purchase.local_entrega} onClick={() => void run(() => chat.confirm(conversation!.id, purchase.id))}>{demoMode ? 'Simular confirmação' : 'Confirmar pedido'} →</button><p className="order-help">{!purchase.cliente || !purchase.local_entrega ? 'Informe nome e local de entrega na conversa.' : 'Quer mudar algo? Peça na conversa antes de confirmar.'}</p></>}{purchase.pedido_id && <p className="receipt" role="status">#{purchase.pedido_id} · {purchase.pedido_status || 'recebido'}</p>}</> : <div className="order-empty"><div aria-hidden="true">▤</div><h3>Seu lanche vem aí.</h3><p>Escolha o que você quer pelo chat. Os detalhes aparecem aqui.</p></div>}<div className="how-it-works"><p className="eyebrow">DO SEU JEITO, SEM COMPLICAÇÃO</p><ol><li><span>01</span> Conte o que quer comer</li><li><span>02</span> Informe onde está</li><li><span>03</span> Confira e confirme</li></ol></div></aside></div>
    <footer className="page-footer"><span>insper eats ✳</span><p>Uma conversa. Um lanche. Um intervalo melhor.</p></footer></main>
  </div>
}
