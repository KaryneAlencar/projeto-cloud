#!/usr/bin/env bash
# Grava a chave do Gemini no Secrets Manager e reinicia o chat para lê-la.
# A chave não passa pelo Terraform: não fica em variáveis, plan ou state.
#
#   ./scripts/set-gemini-key.sh            # pergunta a chave, sem exibi-la
#   ./scripts/set-gemini-key.sh < chave.txt
set -euo pipefail

cd "$(dirname "$0")/.."

for tool in aws terraform; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERRO: '$tool' não encontrado no PATH." >&2; exit 1; }
done

region="$(terraform output -raw region)"
prefix="$(terraform output -raw name_prefix)"
cluster="$(terraform output -raw ecs_cluster_name)"
secret="${prefix}/gemini-api-key"
service="${prefix}-chat-service"

if [[ -t 0 ]]; then
  read -rsp "Chave do Gemini (não será exibida): " key
  echo
else
  IFS= read -r key
fi
# Remove espaços e quebras de linha (CR/LF) nas pontas: iriam para o cabeçalho HTTP.
key="$(tr -d '\r\n' <<<"$key" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
if [[ -z "$key" ]]; then
  echo "ERRO: chave vazia." >&2
  exit 1
fi

# O valor vai por stdin, não pela linha de comando (visível em `ps`).
# printf, e não <<<, para não acrescentar uma quebra de linha ao secret.
printf '%s' "$key" | aws secretsmanager put-secret-value --region "$region" --secret-id "$secret" \
  --secret-string file:///dev/stdin >/dev/null
unset key
echo "Secret ${secret} atualizado."

aws ecs update-service --region "$region" --cluster "$cluster" --service "$service" \
  --force-new-deployment >/dev/null
echo "Novo deployment de ${service} iniciado; aguardando estabilizar..."
aws ecs wait services-stable --region "$region" --cluster "$cluster" --services "$service"

echo "Pronto. Se ai_provider ainda for \"commands\", troque para \"gemini\" em terraform.tfvars e rode terraform apply."
