#!/usr/bin/env bash
# Register a new revision of one task-definition family with a new image and print its
# ARN. Copies the current revision (including its tags) and changes only the image.
# Usage: register_task_definition.sh FAMILY IMAGE   (needs aws, jq and AWS credentials)
set -euo pipefail

family=$1
image=$2
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

aws ecs describe-task-definition --task-definition "$family" --include TAGS > "$work/current.json"
jq --arg image "$image" '
  .taskDefinition
  | .containerDefinitions |= map(.image = $image)
  | del(.taskDefinitionArn, .revision, .status, .requiresAttributes, .compatibilities,
        .registeredAt, .registeredBy, .deregisteredAt)
' "$work/current.json" > "$work/next.json"
tags=$(jq -c '.tags // []' "$work/current.json")
if [ "$tags" != "[]" ]; then
  jq --argjson tags "$tags" '. + {tags: $tags}' "$work/next.json" > "$work/tagged.json"
  mv "$work/tagged.json" "$work/next.json"
fi
aws ecs register-task-definition --cli-input-json "file://$work/next.json" \
  --query taskDefinition.taskDefinitionArn --output text
