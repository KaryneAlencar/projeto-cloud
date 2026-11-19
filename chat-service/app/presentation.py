"""Apresentação das mensagens; não modifica catálogo, estoque ou seleção."""
import re


def customer_message(content):
    # Remove os rótulos técnicos usados nos catálogos antigos, preservando preços,
    # quantidades solicitadas, endereço e o número comercial do pedido (#123).
    content = re.sub(r"\\([*_-])", r"\1", content)
    label = r"(?:ID(?:\s+do\s+produto)?|produto_id|estoque(?:\s+atual)?)"
    content = re.sub(rf"\s*\(\s*(?:\*\*)?{label}(?:\*\*)?\s*:\s*\d+\s*\)", "", content, flags=re.I)
    content = re.sub(rf"(?:\s*[·|]\s*|\s+-\s+)?(?:\*\*)?{label}(?:\*\*)?\s*:\s*\d+\b", "", content, flags=re.I)
    # Formato anterior do modo commands: '· estoque 20', sem dois-pontos.
    content = re.sub(r"\s*[·|]\s*estoque\s+\d+\b", "", content, flags=re.I)
    content = re.sub(r"\s*\(ID\s+\d+\)", "", content, flags=re.I)
    return "\n".join(line.rstrip() for line in content.splitlines()).strip()
