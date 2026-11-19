export type Message = { id: string; papel: 'usuario' | 'assistente'; conteudo: string }
export type Purchase = { id: string; cliente: string; local_entrega: string; total: number; itens: { nome: string; quantidade: number; preco_unitario: number }[]; status: 'preparando' | 'confirmando' | 'confirmado'; pedido_id?: string; pedido_status?: string }
export type Conversation = { id: string; mensagens: Message[]; compra: Purchase | null; processadas?: string[]; confirmacao_habilitada?: boolean }
export const demoMode = import.meta.env.VITE_CHAT_MODE === 'demo'
export const money = (n: number) => n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })
const base = (import.meta.env.VITE_CHAT_API_URL || '/api').replace(/\/$/, '')
const key = (id: string) => `insper-eats:demo:${id}`
const msg = (papel: Message['papel'], conteudo: string): Message => ({ id: crypto.randomUUID(), papel, conteudo })
function save(c: Conversation) { localStorage.setItem(key(c.id), JSON.stringify(c)); return c }
function read(id: string): Conversation {
  try { const raw = localStorage.getItem(key(id)); if (raw) return JSON.parse(raw) } catch { /* handled below */ }
  throw new Error('Conversa não encontrada neste navegador. Inicie uma nova conversa.')
}
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}
export type OrderSummary = { pedido_id: number | string; status: string; total: number }
export type OrderHistory = { escopo: string; pedidos: OrderSummary[] }
let csrf = ''
let initializing: Promise<void> | null = null
async function ensureSession() {
  if (csrf) return
  if (!initializing) initializing = (async () => {
    const response = await fetch(`${base}/chat/sessao`, { method: 'POST', credentials: 'same-origin', signal: AbortSignal.timeout(15000) })
    const value = await response.json().catch(() => null)
    if (!response.ok || typeof value?.csrf_token !== 'string') throw new ApiError(response.status, value?.detail || 'Não foi possível iniciar sua sessão. Tente novamente.')
    csrf = value.csrf_token
  })().finally(() => { initializing = null })
  await initializing
}
async function apiRequest<T>(path: string, body?: unknown, retried = false): Promise<T> {
  let response: Response
  try {
    await ensureSession()
    response = await fetch(`${base}${path}`, {
      method: body === undefined ? 'GET' : 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(body === undefined ? {} : { 'X-CSRF-Token': csrf }) },
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(150000),
    })
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'TimeoutError') throw new Error('O chat excedeu o tempo de espera. Tente novamente.')
    throw new Error('O serviço não respondeu. Confira a conexão e tente novamente.')
  }
  if (response.status === 401 && !retried) { csrf = ''; return apiRequest<T>(path, body, true) }
  const value = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, typeof value?.detail === 'string' ? value.detail : 'Não foi possível concluir. Tente novamente.')
  return value as T
}
async function request(path: string, body?: unknown): Promise<Conversation> {
  const c = await apiRequest<Conversation>(path, body)
  if (typeof c?.id !== 'string' || !Array.isArray(c.mensagens) || !('compra' in c)) throw new Error('Resposta incompatível com o chat.')
  return c
}

const products = [{ nome: 'Brownie', preco_unitario: 8, pattern: /brownie/i }, { nome: 'Cookie', preco_unitario: 6, pattern: /cookie/i }, { nome: 'Pão de queijo', preco_unitario: 5, pattern: /p[aã]o de queijo/i }]
export const chat = {
  async orders(): Promise<OrderHistory> {
    if (!demoMode) {
      const history = await apiRequest<OrderHistory>('/chat/pedidos')
      if (!history || !Array.isArray(history.pedidos) || history.pedidos.some(order => !order || typeof order.status !== 'string' || typeof order.total !== 'number')) throw new Error('Não foi possível interpretar a atualização dos pedidos.')
      return history
    }
    const pedidos: OrderSummary[] = []
    for (let index = 0; index < localStorage.length; index++) {
      const key = localStorage.key(index)
      if (!key?.startsWith('insper-eats:demo:')) continue
      try {
        const c = JSON.parse(localStorage.getItem(key) || '{}') as Conversation
        if (c.compra?.pedido_id) pedidos.push({ pedido_id: c.compra.pedido_id, status: c.compra.pedido_status || 'simulado', total: c.compra.total })
      } catch { /* Ignore unrelated or invalid local entries. */ }
    }
    return { escopo: 'pedidos simulados deste navegador', pedidos }
  },
  storageKey: `insper-eats:conversation:${demoMode ? 'demo' : base}`,
  async create(): Promise<Conversation> { return demoMode ? save({ id: crypto.randomUUID(), mensagens: [msg('assistente', 'Oi! Que bom te ver por aqui. ✳\nEu te ajudo a escolher seu próximo lanche. Quer dar uma olhada no cardápio?')], compra: null, processadas: [] }) : request('/chat/conversas', {}) },
  async get(id: string) { return demoMode ? read(id) : request(`/chat/conversas/${encodeURIComponent(id)}`) },
  async send(id: string, content: string, messageId: string): Promise<Conversation> {
    if (!demoMode) return request(`/chat/conversas/${encodeURIComponent(id)}/mensagens`, { conteudo: content, mensagem_id: messageId })
    const c = read(id)
    if (c.processadas?.includes(messageId)) return c
    let answer = ''
    if (/cancel/i.test(content)) { c.compra = null; answer = 'Seleção cancelada. O que você quer escolher agora?' }
    else if (/card[aá]pio|cat[aá]logo|pre[cç]o|dispon[ií]ve/i.test(content)) answer = 'Cardápio de demonstração:\n' + products.map(p => `${p.nome} · ${money(p.preco_unitario)}`).join('\n') + '\n\nExperimente: “Quero 2 brownies”.'
    else if (products.some(p => p.pattern.test(content))) {
      const itens = products.filter(p => p.pattern.test(content)).map(p => { const match = content.match(new RegExp(`(\\d+)\\s+${p.pattern.source}`, 'i')); return { nome: p.nome, preco_unitario: p.preco_unitario, quantidade: match ? Number(match[1]) : 1 } })
      if (itens.some(p => p.quantidade < 1 || p.quantidade > 20)) answer = 'Na demonstração, escolha entre 1 e 20 unidades de cada produto.'
      else { c.compra = { id: crypto.randomUUID(), cliente: '', local_entrega: '', itens, total: itens.reduce((s, p) => s + p.quantidade * p.preco_unitario, 0), status: 'preparando' }; answer = 'Seleção preparada! Envie “Meu nome é Ana” e depois “Entrega: sala 512, prédio 2”.\nUma nova seleção substitui a anterior nesta demonstração.' }
    } else if (c.compra?.status === 'preparando' && /^(meu nome [ée]|nome:)/i.test(content)) { const name = content.replace(/^(meu nome [ée]|nome:)\s*/i, '').trim(); if (name.length < 2) answer = 'Informe seu nome após “Meu nome é”.'; else { c.compra.cliente = name; answer = 'Nome anotado. Informe “Entrega: sala 512, prédio 2” ou confira o resumo se já informou o local.' } }
    else if (c.compra?.status === 'preparando' && /^entrega:/i.test(content)) { const address = content.replace(/^entrega:\s*/i, '').trim(); if (address.length < 3) answer = 'Informe prédio e sala após “Entrega:”.'; else { c.compra.local_entrega = address; answer = 'Local anotado! Confira o resumo e use o botão para simular a confirmação.' } }
    else if (/entrega/i.test(content)) answer = 'Escolha um produto e informe seu nome. Depois envie “Entrega: sala 512, prédio 2”.'
    else answer = 'Este é um roteiro de demonstração, ainda sem IA. Posso mostrar o cardápio ou preparar brownies, cookies e pão de queijo. Experimente “Quero 2 brownies”.'
    c.mensagens.push(msg('usuario', content), msg('assistente', answer)); c.processadas = [...(c.processadas || []), messageId]; return save(c)
  },
  async confirm(id: string, purchaseId: string): Promise<Conversation> {
    if (!demoMode) return request(`/chat/conversas/${encodeURIComponent(id)}/confirmar`, { compra_id: purchaseId })
    const c = read(id)
    if (!c.compra || c.compra.id !== purchaseId) throw new Error('A seleção mudou. Confira o resumo novamente.')
    if (c.compra.status === 'confirmado') return c
    if (!c.compra.cliente || !c.compra.local_entrega) throw new Error('Informe nome e local de entrega.')
    c.compra.status = 'confirmado'; c.compra.pedido_id = `DEMO-${purchaseId.slice(0, 6).toUpperCase()}`; c.compra.pedido_status = 'simulado'
    c.mensagens.push(msg('assistente', 'Confirmação simulada! Nenhum pedido real foi criado e nenhum estoque foi alterado.')); return save(c)
  },
}
