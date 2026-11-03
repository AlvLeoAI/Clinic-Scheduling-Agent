#!/usr/bin/env bash
# Run a one-off Fargate task, wait until it stops, print its log and fail unless its
# container exited 0. Used by the deploy workflow for the migrate and smoke tasks.
# Usage: run_one_off_task.sh DEPLOY_JSON TASK_DEFINITION_ARN SECURITY_GROUP LOG_GROUP NAME
# NAME is both the container name and the log stream prefix (NAME/NAME/TASK_ID).
set -euo pipefail

cfg=$1
taskdef=$2
sg=$3
logs=$4
name=$5

cluster=$(jq -r .cluster "$cfg")
network=$(jq -c --arg sg "$sg" \
  '{awsvpcConfiguration: {subnets: .subnets, securityGroups: [$sg], assignPublicIp: "ENABLED"}}' "$cfg")
task=$(aws ecs run-task --cluster "$cluster" --task-definition "$taskdef" \
  --launch-type FARGATE --network-configuration "$network" \
  --propagate-tags TASK_DEFINITION --started-by "github-${GITHUB_RUN_ID:-local}" \
  --query 'tasks[0].taskArn' --output text)
case "$task" in
  arn:aws:ecs:*) echo "$name task: $task" ;;
  *) echo "$name task was not started" >&2; exit 1 ;;
esac

aws ecs wait tasks-stopped --cluster "$cluster" --tasks "$task"
result=$(aws ecs describe-tasks --cluster "$cluster" --tasks "$task" \
  --query 'tasks[0].{stopped: stoppedReason, exit: containers[0].exitCode}' --output json)
aws logs get-log-events --log-group-name "$logs" \
  --log-stream-name "$name/$name/${task##*/}" --start-from-head \
  --query 'events[].message' --output text || echo "(no log events)"
echo "$result"
code=$(jq -r '.exit // "none"' <<<"$result")
if [ "$code" != 0 ]; then
  echo "$name exited with $code" >&2
  exit 1
fi
