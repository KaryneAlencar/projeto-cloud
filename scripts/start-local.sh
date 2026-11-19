#!/usr/bin/env bash
# Sobe banco, API, chat e frontend no Docker (equivalente Linux/macOS de start-local.ps1).
# Uso: scripts/start-local.sh [--commands] [--no-build]
#   --commands  usa AI_PROVIDER=commands (roteiro sem chamar a IA)
#   --no-build  não reconstrói as imagens
# Portas: FRONTEND_PORT (8080), API_PORT (8002) e CHAT_PORT (8003), por variável de ambiente.
set -euo pipefail

provider=gemini
build=(--build)
for arg in "$@"; do
    case "$arg" in
        --commands) provider=commands ;;
        --no-build) build=() ;;
        -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
        *) echo "Opção desconhecida: $arg" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
    cp .env.example .env
    echo 'Arquivo .env criado a partir de .env.example. Troque a senha antes do primeiro uso, se quiser.'
fi
if [[ ! -f chat-service/.env ]]; then
    cp chat-service/.env.example chat-service/.env
    echo 'Arquivo chat-service/.env criado. Preencha a chave Gemini para usar IA.'
fi

# Lê uma variável do .env da raiz sem executar o arquivo.
env_value() {
    sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" .env | tail -n 1 | sed -e 's/[[:space:]]*$//' -e 's/^"\(.*\)"$/\1/' -e "s/^'\(.*\)'$/\1/"
}

for field in POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB; do
    if [[ -z "$(env_value "$field")" ]]; then
        echo "Preencha $field no arquivo .env (raiz do repositório)." >&2
        exit 1
    fi
done

# .env antigo (criado para o start-local.ps1) pode não ter APP_DATABASE_URL: monta a partir do banco.
if [[ -z "${APP_DATABASE_URL:-}" && -z "$(env_value APP_DATABASE_URL)" ]]; then
    APP_DATABASE_URL="$(DB_USER="$(env_value POSTGRES_USER)" DB_PASSWORD="$(env_value POSTGRES_PASSWORD)" DB_NAME="$(env_value POSTGRES_DB)" python3 -c '
import os
from urllib.parse import quote
q = lambda name: quote(os.environ[name], safe="")
print(f"postgresql+psycopg://{q(\"DB_USER\")}:{q(\"DB_PASSWORD\")}@db:5432/{q(\"DB_NAME\")}")')"
    export APP_DATABASE_URL
fi

export AI_PROVIDER="$provider"
export COOKIE_SECURE=false
export FRONTEND_PORT="${FRONTEND_PORT:-8080}" API_PORT="${API_PORT:-8002}" CHAT_PORT="${CHAT_PORT:-8003}"

if ! docker compose -f compose.yaml -f compose.app.yaml up -d --wait --wait-timeout 240 "${build[@]}"; then
    echo 'O Docker não concluiu a inicialização. Verifique o Docker, as portas e os logs dos serviços.' >&2
    exit 1
fi

# Catálogo inicial (o mesmo de seed_products em terraform/variables.tf), só se estiver vazio.
API_URL="http://127.0.0.1:${API_PORT}" python3 - <<'PY'
import json
import os
from urllib.request import Request, urlopen

base = os.environ["API_URL"]
catalogo = [
    {"nome": "Brownie", "preco": "8.00", "estoque": 40},
    {"nome": "Pão de queijo", "preco": "6.50", "estoque": 60},
    {"nome": "Sanduíche natural", "preco": "16.00", "estoque": 30},
    {"nome": "Salada de frutas", "preco": "12.00", "estoque": 25},
    {"nome": "Café coado", "preco": "5.00", "estoque": 80},
    {"nome": "Suco de laranja", "preco": "9.00", "estoque": 40},
]
with urlopen(f"{base}/produtos", timeout=10) as resposta:
    existentes = json.load(resposta)
if existentes:
    print(f"Catálogo existente preservado ({len(existentes)} produtos).")
else:
    for produto in catalogo:
        requisicao = Request(f"{base}/produtos", data=json.dumps(produto).encode(),
                             headers={"Content-Type": "application/json"}, method="POST")
        urlopen(requisicao, timeout=10).close()
    print(f"Catálogo inicial cadastrado ({len(catalogo)} produtos).")
PY

echo "Insper Eats disponível em http://localhost:${FRONTEND_PORT}"
echo "Modo: ${provider}. Os pedidos confirmados são registrados no banco local existente."
