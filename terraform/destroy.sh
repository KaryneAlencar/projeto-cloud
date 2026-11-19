#!/usr/bin/env bash
# Desmonta tudo o que ./deploy.sh criou, sem perguntas: o ambiente inteiro e,
# em seguida, o bucket do state remoto.
#
#   export AWS_PROFILE=insper-eats
#   ./destroy.sh              # ambiente + bucket do state
#   ./destroy.sh --keep-state # só o ambiente; o bucket fica para o próximo deploy
#
# ATENÇÃO: apaga o banco (sem snapshot final, com os padrões), as imagens e os
# secrets. Depois dele, ./deploy.sh recria tudo do zero.
set -euo pipefail

cd "$(dirname "$0")"

keep_state=false
[[ "${1:-}" == "--keep-state" ]] && keep_state=true

for tool in terraform aws; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERRO: '$tool' não encontrado no PATH." >&2; exit 1; }
done
aws sts get-caller-identity --query Account --output text >/dev/null ||
  { echo "ERRO: sem credenciais AWS válidas (aws sso login? AWS_PROFILE definido?)." >&2; exit 1; }

var_file=()
[[ -f terraform.tfvars ]] && var_file=(-var-file=../terraform.tfvars)

# --- 1. Ambiente ------------------------------------------------------------
if [[ -f backend.hcl ]]; then
  echo "== Destruindo o ambiente"
  terraform init -input=false -reconfigure -backend-config=backend.hcl >/dev/null
  region="$(terraform output -raw region 2>/dev/null || true)"
  prefix="$(terraform output -raw name_prefix 2>/dev/null || true)"
  # A variável efêmera da chave não tem valor no destroy; qualquer texto serve.
  TF_VAR_gemini_api_key="${TF_VAR_gemini_api_key:-nao-usada-no-destroy}" \
    terraform destroy -input=false -auto-approve

  # O Container Insights pode recriar seu log group com um lote atrasado de
  # métricas, fora do state; se sobrar, o próximo deploy falharia ao criá-lo.
  if [[ -n "$region" && -n "$prefix" ]]; then
    aws logs delete-log-group --region "$region" \
      --log-group-name "/aws/ecs/containerinsights/${prefix}-cluster/performance" 2>/dev/null || true
  fi
else
  echo "backend.hcl não encontrado: nenhum ambiente registrado neste diretório."
fi

# --- 2. Bucket do state -----------------------------------------------------
if $keep_state; then
  echo "Bucket do state mantido (--keep-state)."
  exit 0
fi

echo "== Removendo o bucket do state remoto"
terraform -chdir=bootstrap init -input=false >/dev/null
if terraform -chdir=bootstrap state list 2>/dev/null | grep -qx 'aws_s3_bucket.state'; then
  # O bucket é versionado: force_destroy precisa estar gravado no state antes
  # do destroy para que as versões antigas do state sejam apagadas junto.
  terraform -chdir=bootstrap apply -input=false -auto-approve \
    ${var_file[@]+"${var_file[@]}"} -var force_destroy=true
  terraform -chdir=bootstrap destroy -input=false -auto-approve \
    ${var_file[@]+"${var_file[@]}"} -var force_destroy=true
else
  echo "O bucket do state não está no state local do bootstrap; nada a remover."
fi
rm -f backend.hcl gemini.auto.tfvars

echo "Ambiente removido."
