# Prepara o terminal para o deploy na AWS. Use com "source", a partir de
# qualquer pasta do repositório:
#
#   source scripts/aws-env.sh
#   aws configure sso        # só na primeira vez; perfil: insper-eats
#   aws sso login --profile insper-eats   # quando a sessão expirar
#   cd terraform && ./deploy.sh
#
# Coloca no PATH o Terraform e a AWS CLI instalados em .venv/ (sem sudo) e
# exporta a chave do Gemini de chat-service/.env, sem exibi-la.

# "builtin"/"command": num terminal interativo, cd, sed e head podem ser aliases
# ou funções (zoxide, por exemplo) que imprimem texto e corromperiam o caminho.
_ie_root="$(builtin cd "$(command dirname "${BASH_SOURCE[0]:-$0}")/.." >/dev/null 2>&1 && builtin pwd)"

case ":$PATH:" in
  *":$_ie_root/.venv/bin:"*) ;;
  *) export PATH="$_ie_root/.venv/bin:$PATH" ;;
esac

export AWS_REGION="${AWS_REGION:-sa-east-1}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-$AWS_REGION}"

if [ -z "${TF_VAR_gemini_api_key:-}" ] && [ -f "$_ie_root/chat-service/.env" ]; then
  _ie_key="$(command sed -n 's/^GEMINI_API_KEY=//p' "$_ie_root/chat-service/.env" | command head -n 1 | command tr -d '\r')"
  [ -n "$_ie_key" ] && export TF_VAR_gemini_api_key="$_ie_key"
  unset _ie_key
fi

# Perfil criado por "aws configure sso" (portal de acesso da AWS).
if [ -z "${AWS_PROFILE:-}" ] && command aws configure list-profiles 2>/dev/null | command grep -qx 'insper-eats'; then
  export AWS_PROFILE=insper-eats
fi

for _ie_tool in terraform aws docker; do
  if command -v "$_ie_tool" >/dev/null 2>&1; then
    echo "ok     $_ie_tool"
  else
    echo "FALTA  $_ie_tool"
  fi
done
if [ -n "${TF_VAR_gemini_api_key:-}" ]; then
  echo "ok     chave do Gemini carregada de chat-service/.env"
else
  echo "aviso  sem chave do Gemini: o chat sobe em modo de comandos"
fi
if aws sts get-caller-identity --query Account --output text >/dev/null 2>&1; then
  echo "ok     conta AWS $(aws sts get-caller-identity --query Account --output text), região $AWS_REGION"
else
  echo "FALTA  login na AWS: rode 'aws sso login --profile insper-eats' (ou 'aws configure sso' na primeira vez)"
fi
unset _ie_root _ie_tool
