import type { ReactNode } from 'react'

// Formatação limitada a texto, negrito e listas. React mantém HTML como texto.
function inline(text: string): ReactNode[] {
  return text.split(/(\*\*[^*\n]+\*\*)/g).map((part, index) =>
    part.startsWith('**') && part.endsWith('**') && part.length > 4
      ? <strong key={index}>{part.slice(2, -2)}</strong>
      : part.replaceAll('**', ''),
  )
}

export default function MessageContent({ text }: { text: string }) {
  const lines = text.replace(/\\([*_-])/g, '$1').split('\n')
  const blocks: ReactNode[] = []
  let paragraph: string[] = []
  let bullets: string[] = []

  function flushParagraph() {
    if (paragraph.length) {
      blocks.push(<p key={blocks.length}>{inline(paragraph.join('\n'))}</p>)
      paragraph = []
    }
  }
  function flushBullets() {
    if (bullets.length) {
      blocks.push(<ul key={blocks.length}>{bullets.map((item, index) => <li key={index}>{inline(item)}</li>)}</ul>)
      bullets = []
    }
  }

  for (const line of lines) {
    const bullet = line.match(/^\s*[-*•]\s+(.+)$/)
    if (bullet) {
      flushParagraph()
      bullets.push(bullet[1])
    } else {
      flushBullets()
      if (!line.trim()) flushParagraph()
      else paragraph.push(line)
    }
  }
  flushParagraph()
  flushBullets()
  return <div className="message-content">{blocks}</div>
}
