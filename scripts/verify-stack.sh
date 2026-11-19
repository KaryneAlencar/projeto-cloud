#!/usr/bin/env bash
# Sobe o ambiente descartável de verificação (porta 18080) e roda scripts/verify_stack.py.
# Equivalente Linux/macOS de verify-stack.ps1. Uso: scripts/verify-stack.sh [--no-build]
set -euo pipefail

build=(--build)
for arg in "$@"; do
    case "$arg" in
        --no-build) build=() ;;
        *) echo "Opção desconhecida: $arg" >&2; exit 2 ;;
    esac
done

cd "$(dirname "$0")/.."

if ! docker compose -p insper-eats-verification -f compose.verify.yaml up -d --wait --wait-timeout 300 "${build[@]}"; then
    echo 'O ambiente de verificação não iniciou.' >&2
    exit 1
fi
if ! python3 scripts/verify_stack.py; then
    echo 'A verificação encontrou uma falha.' >&2
    exit 1
fi
echo 'Relatório: work/verification.json. Ambiente disponível na porta 18080.'
