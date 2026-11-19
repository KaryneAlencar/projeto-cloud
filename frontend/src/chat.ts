export type Message = {
  id: string
  papel: 'usuario' | 'assistente'
  conteudo: string
  // Enviado pelo Chat Service (ISO 8601). O modo demonstração não o grava.
  criado_em?: string
}
export type PurchaseItem = { nome: string; quantidade: number; preco_unitario: number }
export type Purchase = {
  id: string
  cliente: string
  local_entrega: string
  total: number
  itens: PurchaseItem[]
  status: 'preparando' | 'confirmando' | 'confirmado'
  pedido_id?: string
  pedido_status?: string
}
export type Conversation = {
  id: string
  mensagens: Message[]
  compra: Purchase | null
  processadas?: string[]
  confirmacao_habilitada?: boolean
}
export type OrderSummary = { pedido_id: number | string; status: string; total: number }
export type OrderHistory = { escopo: string; pedidos: OrderSummary[] }

export const demoMode = import.meta.env.VITE_CHAT_MODE === 'demo'
export const money = (n: number) => n.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' })

const base = (import.meta.env.VITE_CHAT_API_URL || '/api').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// --- Modo integrado: sessão anônima (cookie HttpOnly) + token CSRF em memória ---

let csrf = ''
let initializing: Promise<void> | null = null

async function ensureSession() {
  if (csrf) return
  if (!initializing) {
    initializing = (async () => {
      const response = await fetch(`${base}/chat/sessao`, {
        method: 'POST',
        credentials: 'same-origin',
        signal: AbortSignal.timeout(15000),
      })
      const value = await response.json().catch(() => null)
      if (!response.ok || typeof value?.csrf_token !== 'string') {
        throw new ApiError(response.status, value?.detail || 'Não foi possível iniciar sua sessão. Tente novamente.')
      }
      csrf = value.csrf_token
    })().finally(() => { initializing = null })
  }
  await initializing
}

async function apiRequest<T>(path: string, body?: unknown, retried = false): Promise<T> {
  const write = body !== undefined
  let response: Response
  let token = ''
  try {
    await ensureSession()
    token = csrf
    response = await fetch(`${base}${path}`, {
      method: write ? 'POST' : 'GET',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(write ? { 'X-CSRF-Token': token } : {}) },
      body: write ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(150000),
    })
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (error instanceof DOMException && error.name === 'TimeoutError') {
      throw new Error('O chat excedeu o tempo de espera. Tente novamente.')
    }
    throw new Error('O serviço não respondeu. Confira a conexão e tente novamente.')
  }
  // 401: a sessão expirou. 403 em escrita: o token CSRF em memória não pertence mais ao
  // cookie atual (outra aba renovou a sessão, por exemplo). Nos dois casos o servidor
  // recusou antes de processar, então renovar o token e repetir uma vez é seguro.
  if ((response.status === 401 || (write && response.status === 403)) && !retried) {
    // Só descarta o token que esta requisição usou; outra pode já tê-lo renovado.
    if (csrf === token) csrf = ''
    return apiRequest<T>(path, body, true)
  }
  const value = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(
      response.status,
      typeof value?.detail === 'string' ? value.detail : 'Não foi possível concluir. Tente novamente.',
    )
  }
  return value as T
}

function isConversation(c: unknown): c is Conversation {
  const value = c as Conversation | null
  return typeof value?.id === 'string' && Array.isArray(value.mensagens) && 'compra' in value
}

async function request(path: string, body?: unknown): Promise<Conversation> {
  const c = await apiRequest<Conversation>(path, body)
  if (!isConversation(c)) throw new Error('Resposta incompatível com o chat.')
  return c
}

// --- Modo demonstração: roteiro determinístico guardado no localStorage ---

const demoPrefix = 'insper-eats:demo:'
const key = (id: string) => `${demoPrefix}${id}`
const msg = (papel: Message['papel'], conteudo: string): Message => ({ id: crypto.randomUUID(), papel, conteudo })

function save(c: Conversation) {
  localStorage.setItem(key(c.id), JSON.stringify(c))
  return c
}

function read(id: string): Conversation {
  try {
    const raw = localStorage.getItem(key(id))
    const c: unknown = raw ? JSON.parse(raw) : null
    if (isConversation(c)) return c
  } catch { /* handled below */ }
  throw new Error('Conversa não encontrada neste navegador. Inicie uma nova conversa.')
}

const products = [
  { nome: 'Brownie', preco_unitario: 8, pattern: /brownie/i },
  { nome: 'Cookie', preco_unitario: 6, pattern: /cookie/i },
  { nome: 'Pão de queijo', preco_unitario: 5, pattern: /p[aã]o de queijo/i },
]

const demoGreeting = 'Oi! Que bom te ver por aqui. ✳\nEu te ajudo a escolher seu próximo lanche. Quer dar uma olhada no cardápio?'

function demoSelection(content: string): PurchaseItem[] {
  return products.filter(p => p.pattern.test(content)).map(p => {
    const match = content.match(new RegExp(`(\\d+)\\s+${p.pattern.source}`, 'i'))
    return { nome: p.nome, preco_unitario: p.preco_unitario, quantidade: match ? Number(match[1]) : 1 }
  })
}

// Aplica a mensagem à conversa de demonstração (pode alterar c.compra) e devolve a resposta.
function demoAnswer(c: Conversation, content: string): string {
  if (/cancel/i.test(content)) {
    c.compra = null
    return 'Seleção cancelada. O que você quer escolher agora?'
  }
  if (/card[aá]pio|cat[aá]logo|pre[cç]o|dispon[ií]ve/i.test(content)) {
    return 'Cardápio de demonstração:\n'
      + products.map(p => `${p.nome} · ${money(p.preco_unitario)}`).join('\n')
      + '\n\nExperimente: “Quero 2 brownies”.'
  }
  if (products.some(p => p.pattern.test(content))) {
    const itens = demoSelection(content)
    if (itens.some(p => p.quantidade < 1 || p.quantidade > 20)) {
      return 'Na demonstração, escolha entre 1 e 20 unidades de cada produto.'
    }
    c.compra = {
      id: crypto.randomUUID(),
      cliente: '',
      local_entrega: '',
      itens,
      total: itens.reduce((s, p) => s + p.quantidade * p.preco_unitario, 0),
      status: 'preparando',
    }
    return 'Seleção preparada! Envie “Meu nome é Ana” e depois “Entrega: sala 512, prédio 2”.\nUma nova seleção substitui a anterior nesta demonstração.'
  }
  if (c.compra?.status === 'preparando' && /^(meu nome [ée]|nome:)/i.test(content)) {
    const name = content.replace(/^(meu nome [ée]|nome:)\s*/i, '').trim()
    if (name.length < 2) return 'Informe seu nome após “Meu nome é”.'
    c.compra.cliente = name
    return 'Nome anotado. Informe “Entrega: sala 512, prédio 2” ou confira o resumo se já informou o local.'
  }
  if (c.compra?.status === 'preparando' && /^entrega:/i.test(content)) {
    const address = content.replace(/^entrega:\s*/i, '').trim()
    if (address.length < 3) return 'Informe prédio e sala após “Entrega:”.'
    c.compra.local_entrega = address
    return 'Local anotado! Confira o resumo e use o botão para simular a confirmação.'
  }
  if (/entrega/i.test(content)) {
    return 'Escolha um produto e informe seu nome. Depois envie “Entrega: sala 512, prédio 2”.'
  }
  return 'Este é um roteiro de demonstração, ainda sem IA. Posso mostrar o cardápio ou preparar brownies, cookies e pão de queijo. Experimente “Quero 2 brownies”.'
}

function demoOrders(): OrderHistory {
  const pedidos: OrderSummary[] = []
  for (let index = 0; index < localStorage.length; index++) {
    const entry = localStorage.key(index)
    if (!entry?.startsWith(demoPrefix)) continue
    try {
      const c = JSON.parse(localStorage.getItem(entry) || '{}') as Conversation
      if (c.compra?.pedido_id) {
        pedidos.push({ pedido_id: c.compra.pedido_id, status: c.compra.pedido_status || 'simulado', total: c.compra.total })
      }
    } catch { /* Ignore unrelated or invalid local entries. */ }
  }
  return { escopo: 'pedidos simulados deste navegador', pedidos }
}

function isOrderHistory(history: OrderHistory | null): history is OrderHistory {
  return !!history && Array.isArray(history.pedidos) && history.pedidos.every(
    order => order && typeof order.status === 'string' && typeof order.total === 'number',
  )
}

export const chat = {
  storageKey: `insper-eats:conversation:${demoMode ? 'demo' : base}`,

  async orders(): Promise<OrderHistory> {
    if (demoMode) return demoOrders()
    const history = await apiRequest<OrderHistory | null>('/chat/pedidos')
    if (!isOrderHistory(history)) throw new Error('Não foi possível interpretar a atualização dos pedidos.')
    return history
  },

  async create(): Promise<Conversation> {
    if (!demoMode) return request('/chat/conversas', {})
    return save({ id: crypto.randomUUID(), mensagens: [msg('assistente', demoGreeting)], compra: null, processadas: [] })
  },

  async get(id: string): Promise<Conversation> {
    return demoMode ? read(id) : request(`/chat/conversas/${encodeURIComponent(id)}`)
  },

  async send(id: string, content: string, messageId: string): Promise<Conversation> {
    if (!demoMode) {
      return request(`/chat/conversas/${encodeURIComponent(id)}/mensagens`, { conteudo: content, mensagem_id: messageId })
    }
    const c = read(id)
    if (c.processadas?.includes(messageId)) return c
    const answer = demoAnswer(c, content)
    c.mensagens.push(msg('usuario', content), msg('assistente', answer))
    c.processadas = [...(c.processadas || []), messageId]
    return save(c)
  },

  async confirm(id: string, purchaseId: string): Promise<Conversation> {
    if (!demoMode) return request(`/chat/conversas/${encodeURIComponent(id)}/confirmar`, { compra_id: purchaseId })
    const c = read(id)
    if (!c.compra || c.compra.id !== purchaseId) throw new Error('A seleção mudou. Confira o resumo novamente.')
    if (c.compra.status === 'confirmado') return c
    if (!c.compra.cliente || !c.compra.local_entrega) throw new Error('Informe nome e local de entrega.')
    c.compra.status = 'confirmado'
    c.compra.pedido_id = `DEMO-${purchaseId.slice(0, 6).toUpperCase()}`
    c.compra.pedido_status = 'simulado'
    c.mensagens.push(msg('assistente', 'Confirmação simulada! Nenhum pedido real foi criado e nenhum estoque foi alterado.'))
    return save(c)
  },
}
