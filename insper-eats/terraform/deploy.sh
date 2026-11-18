#!/usr/bin/env bash
# Implanta o Insper Eats do zero com um comando: bucket do state remoto,
# imagens, infraestrutura, banco e serviços. Não faz perguntas.
#
#   export AWS_PROFILE=insper-eats            # ou outras credenciais AWS
#   export TF_VAR_gemini_api_key="..."        # chave do Gemini (não vai para o state)
#   ./deploy.sh
#
# Repetir o comando é seguro: só aplica o que mudou.
set -euo pipefail

cd "$(dirname "$0")"

for tool in terraform aws docker; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERRO: '$tool' não encontrado no PATH." >&2; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "ERRO: o Docker não está em execução." >&2; exit 1; }
account="$(aws sts get-caller-identity --query Account --output text)" ||
  { echo "ERRO: sem credenciais AWS válidas (aws sso login?)." >&2; exit 1; }
echo "Conta AWS: ${account}"

if [[ -z "${TF_VAR_gemini_api_key:-}" ]]; then
  echo "AVISO: TF_VAR_gemini_api_key não definida; o chat só responde com ai_provider = \"commands\"." >&2
fi

# terraform.tfvars é opcional: todos os valores têm padrão.
var_file=()
[[ -f terraform.tfvars ]] && var_file=(-var-file=../terraform.tfvars)

# 1. State remoto. backend.hcl presente indica que o bucket já foi criado.
if [[ ! -f backend.hcl ]]; then
  echo "== Criando o bucket do state remoto"
  terraform -chdir=bootstrap init -input=false
  terraform -chdir=bootstrap apply -input=false -auto-approve ${var_file[@]+"${var_file[@]}"}
  terraform -chdir=bootstrap output -raw backend_config > backend.hcl
fi

# 2. Ambiente completo.
echo "== Implantando o ambiente (25 a 35 minutos na primeira vez)"
terraform init -input=false -reconfigure -backend-config=backend.hcl
terraform apply -input=false -auto-approve

echo
echo "Aplicação: $(terraform output -raw app_url)"
echo "Verificação: python3 scripts/verify_deploy.py"
