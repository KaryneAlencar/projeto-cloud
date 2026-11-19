#!/usr/bin/env bash
# Constrói uma imagem e envia ao ECR. Chamado pelo Terraform (ecr.tf).
# Não faz nada quando a tag já existe no repositório.
set -euo pipefail

: "${AWS_REGION:?defina AWS_REGION}"
: "${REPOSITORY_NAME:?defina REPOSITORY_NAME}"
: "${REPOSITORY_URL:?defina REPOSITORY_URL}"
: "${IMAGE_TAG:?defina IMAGE_TAG}"
: "${BUILD_CONTEXT:?defina BUILD_CONTEXT}"
: "${DOCKERFILE:?defina DOCKERFILE}"

for tool in aws docker; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "ERRO: '$tool' não encontrado no PATH. Instale-o ou rode o apply com -var build_images=false." >&2
    exit 1
  fi
done

image="${REPOSITORY_URL}:${IMAGE_TAG}"
registry="${REPOSITORY_URL%%/*}"

if aws ecr describe-images --region "$AWS_REGION" --repository-name "$REPOSITORY_NAME" \
  --image-ids "imageTag=${IMAGE_TAG}" >/dev/null 2>&1; then
  echo "Imagem ${image} já existe no ECR; nada a fazer."
  exit 0
fi

echo "Autenticando o Docker em ${registry}"
# O Terraform roda os quatro builds em paralelo e todos gravam o mesmo
# ~/.docker/config.json: o login é serializado para não corromper o arquivo.
login() {
  aws ecr get-login-password --region "$AWS_REGION" |
    docker login --username AWS --password-stdin "$registry" >/dev/null
}
if command -v flock >/dev/null 2>&1; then
  (
    flock 9
    login
  ) 9>"${TMPDIR:-/tmp}/insper-eats-docker-login.lock"
else
  login
fi

echo "Construindo ${image}"
# As instâncias do cluster são x86_64, mesmo quando o build roda em ARM (Mac).
# Sem atestados de proveniência, o ECR recebe um manifesto simples.
BUILDX_NO_DEFAULT_ATTESTATIONS=1 docker build \
  --platform linux/amd64 \
  --file "${BUILD_CONTEXT}/${DOCKERFILE}" \
  --tag "$image" \
  "$BUILD_CONTEXT"

echo "Enviando ${image}"
docker push "$image"
