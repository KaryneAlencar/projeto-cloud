#!/usr/bin/env bash
# Executa a task db-init em Fargate e espera o resultado.
# Chamado pelo Terraform (db_init.tf); também pode ser rodado à mão.
set -euo pipefail

: "${AWS_REGION:?defina AWS_REGION}"
: "${CLUSTER:?defina CLUSTER}"
: "${TASK_DEFINITION:?defina TASK_DEFINITION}"
: "${SUBNETS:?defina SUBNETS (ids separados por vírgula)}"
: "${SECURITY_GROUP:?defina SECURITY_GROUP}"
: "${LOG_GROUP:?defina LOG_GROUP}"
TIMEOUT_SECONDS="${TIMEOUT_SECONDS:-900}"

if ! command -v aws >/dev/null 2>&1; then
  echo "ERRO: AWS CLI não encontrada no PATH (necessária para executar a task db-init)." >&2
  exit 1
fi

echo "Iniciando a task db-init no cluster ${CLUSTER}"
run_output="$(aws ecs run-task \
  --region "$AWS_REGION" \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_DEFINITION" \
  --capacity-provider-strategy capacityProvider=FARGATE,weight=1 \
  --network-configuration "awsvpcConfiguration={subnets=[${SUBNETS}],securityGroups=[${SECURITY_GROUP}],assignPublicIp=DISABLED}" \
  --started-by terraform-db-init \
  --query '[tasks[0].taskArn, failures[0].reason]' \
  --output text)"

task_arn="$(awk '{print $1}' <<<"$run_output")"
if [[ -z "$task_arn" || "$task_arn" == "None" ]]; then
  echo "ERRO: o ECS não aceitou a task: ${run_output}" >&2
  exit 1
fi
task_id="${task_arn##*/}"
echo "Task ${task_id} criada; aguardando o término (até ${TIMEOUT_SECONDS}s)"

deadline=$((SECONDS + TIMEOUT_SECONDS))
status=""
while [[ "$status" != "STOPPED" ]]; do
  if ((SECONDS >= deadline)); then
    echo "ERRO: a task db-init não terminou em ${TIMEOUT_SECONDS}s; interrompendo-a." >&2
    aws ecs stop-task --region "$AWS_REGION" --cluster "$CLUSTER" --task "$task_arn" \
      --reason "timeout do db-init" >/dev/null || true
    exit 1
  fi
  sleep 10
  status="$(aws ecs describe-tasks --region "$AWS_REGION" --cluster "$CLUSTER" --tasks "$task_arn" \
    --query 'tasks[0].lastStatus' --output text)"
  echo "  status: ${status}"
done

read -r exit_code stopped_reason < <(aws ecs describe-tasks --region "$AWS_REGION" --cluster "$CLUSTER" \
  --tasks "$task_arn" --query 'tasks[0].[containers[0].exitCode, stoppedReason]' --output text)

echo "--- logs da task (${LOG_GROUP}) ---"
aws logs get-log-events --region "$AWS_REGION" --log-group-name "$LOG_GROUP" \
  --log-stream-name "db-init/db-init/${task_id}" --query 'events[].message' --output text 2>/dev/null |
  tr '\t' '\n' || echo "(sem logs disponíveis)"
echo "-----------------------------------"

if [[ "$exit_code" != "0" ]]; then
  echo "ERRO: db-init terminou com código '${exit_code}'. Motivo informado pelo ECS: ${stopped_reason:-desconhecido}" >&2
  exit 1
fi
echo "db-init concluído com sucesso."
