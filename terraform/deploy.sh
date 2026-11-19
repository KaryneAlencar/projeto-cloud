#!/usr/bin/env bash
# Implanta o Insper Eats do zero com um comando: bucket do state remoto,
# imagens, infraestrutura, banco e serviços. Não faz perguntas.
#
#   export AWS_PROFILE=insper-eats            # ou outras credenciais AWS
#   export TF_VAR_gemini_api_key="..."        # chave do Gemini (não vai para o state)
#   ./deploy.sh
#
# Repetir o comando é seguro: só aplica o que mudou. Para desmontar: ./destroy.sh
#
# As credenciais vêm do ambiente (AWS_PROFILE ou variáveis AWS_*). Se usar
# aws_profile em terraform.tfvars, exporte o mesmo perfil em AWS_PROFILE.
set -euo pipefail

cd "$(dirname "$0")"

for tool in terraform aws docker; do
  command -v "$tool" >/dev/null 2>&1 || { echo "ERRO: '$tool' não encontrado no PATH." >&2; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "ERRO: o Docker não está em execução." >&2; exit 1; }
account="$(aws sts get-caller-identity --query Account --output text)" ||
  { echo "ERRO: sem credenciais AWS válidas (aws sso login? AWS_PROFILE definido?)." >&2; exit 1; }
echo "Conta AWS: ${account}"

# terraform.tfvars é opcional: todos os valores têm padrão.
var_file=()
[[ -f terraform.tfvars ]] && var_file=(-var-file=../terraform.tfvars)

# --- Chave do Gemini --------------------------------------------------------
# O secret só é regravado quando gemini_api_key_version muda. A versão é
# derivada da própria chave e gravada em gemini.auto.tfvars (ignorado pelo
# Git): a mesma chave não gera mudança, uma chave nova é gravada sem passo
# manual, e um "terraform apply" direto, sem a chave no ambiente, lê a mesma
# versão do arquivo e não toca no secret.
if [[ -n "${TF_VAR_gemini_api_key:-}" ]]; then
  checksum="$(printf '%s' "$TF_VAR_gemini_api_key" | cksum | cut -d' ' -f1)"
  echo "gemini_api_key_version = $((checksum % 1000000 + 2))" > gemini.auto.tfvars
elif [[ ! -f gemini.auto.tfvars ]]; then
  echo "AVISO: TF_VAR_gemini_api_key não definida; implantando o chat em modo de comandos (sem IA)." >&2
  echo "       Para usar o Gemini, exporte a chave e rode ./deploy.sh de novo." >&2
  # Variável de ambiente tem precedência menor que terraform.tfvars: se o
  # arquivo fixar ai_provider = "gemini", ele continua valendo.
  export TF_VAR_ai_provider="${TF_VAR_ai_provider:-commands}"
fi

# --- 1. State remoto --------------------------------------------------------
# Sempre executado: é idempotente, e backend.hcl é regenerado a cada vez. Assim
# o comando funciona depois de um destroy e também num clone novo do
# repositório, em que o state local do bootstrap não existe mais.
echo "== Bucket do state remoto"
terraform -chdir=bootstrap init -input=false >/dev/null
if ! terraform -chdir=bootstrap state list 2>/dev/null | grep -qx 'aws_s3_bucket.state'; then
  bucket="$(echo 'local.bucket_name' |
    terraform -chdir=bootstrap console ${var_file[@]+"${var_file[@]}"} 2>/dev/null | tr -d '"')"
  if [[ -n "$bucket" ]] && aws s3api head-bucket --bucket "$bucket" >/dev/null 2>&1; then
    echo "Bucket ${bucket} já existe; adotando-o no state do bootstrap."
    terraform -chdir=bootstrap import -input=false ${var_file[@]+"${var_file[@]}"} \
      aws_s3_bucket.state "$bucket" >/dev/null
  fi
fi
terraform -chdir=bootstrap apply -input=false -auto-approve ${var_file[@]+"${var_file[@]}"}
terraform -chdir=bootstrap output -raw backend_config > backend.hcl

terraform init -input=false -reconfigure -backend-config=backend.hcl

# --- 2. Cota de vCPU --------------------------------------------------------
# Os quatro serviços ocupam 4 instâncias t3.medium em repouso (8 vCPU) e até
# ecs_asg_max_size no pico. Com cota menor, o Auto Scaling Group não consegue
# lançar as instâncias e o apply só falharia depois de 40 minutos de espera.
region="$(echo 'var.region' | terraform console 2>/dev/null | tr -d '"')"
region="${region:-${AWS_REGION:-sa-east-1}}"
quota="$(aws service-quotas get-service-quota --region "$region" --service-code ec2 \
  --quota-code L-1216C47A --query 'Quota.Value' --output text 2>/dev/null || true)"
if [[ "$quota" =~ ^[0-9.]+$ ]]; then
  quota="${quota%.*}"
  if ((quota < 8)); then
    echo "ERRO: a cota de vCPU On-Demand em ${region} é ${quota}; o ambiente precisa de 8 em repouso." >&2
    echo "      Peça aumento de 'Running On-Demand Standard instances' (L-1216C47A) em Service Quotas." >&2
    exit 1
  elif ((quota < 20)); then
    echo "AVISO: cota de vCPU On-Demand em ${region}: ${quota}. Basta para o repouso (8)," >&2
    echo "       mas o scale-out completo (10 instâncias, 20 vCPU) não cabe." >&2
  fi
else
  echo "AVISO: não foi possível consultar a cota de vCPU em ${region}; seguindo sem conferir." >&2
fi

# --- 3. Ambiente completo ---------------------------------------------------
echo "== Implantando o ambiente (30 a 40 minutos na primeira vez)"
terraform apply -input=false -auto-approve

echo
echo "Aplicação: $(terraform output -raw app_url)"
echo "Verificação: python3 scripts/verify_deploy.py"
