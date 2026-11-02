#!/usr/bin/env bash
# Install the pinned Terraform and TFLint binaries into $1 (default ~/.local/bin),
# verifying each download against the SHA-256 recorded here. Used by CI and locally.
# checkov is separate: pip install --require-hashes -r infra/tools/checkov.lock
set -euo pipefail

TERRAFORM_VERSION=1.16.6
TFLINT_VERSION=0.64.0
declare -A SHA256=(
  [terraform_linux_amd64]=38034b38d03096399a7a1264a14561a8029b2b496fd1f169452656e53968f1b7
  [terraform_linux_arm64]=a750b5a11038f165846b2658c40c88cd7070aa67a61bab431a14ba27928ea9ea
  [tflint_linux_amd64]=cca9d13e2e1d7a2c627af60ff899a3c9b74212899416aeb96ec764d2ef954537
  [tflint_linux_arm64]=560da89aacf59389d4eb029730dd5b109b7288096c32f2726a0d9e783a5ea8eb
)

dest=${1:-$HOME/.local/bin}
case "$(uname -m)" in
  x86_64) arch=amd64 ;;
  aarch64 | arm64) arch=arm64 ;;
  *) echo "unsupported architecture: $(uname -m)" >&2; exit 1 ;;
esac
[ "$(uname -s)" = Linux ] || { echo "Linux only; see the release pages for other systems" >&2; exit 1; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

fetch() { # name url
  curl -fsSL --retry 3 -o "$work/$1.zip" "$2"
  echo "${SHA256[$1_linux_$arch]}  $work/$1.zip" | sha256sum -c --quiet -
  unzip -oq "$work/$1.zip" "$1" -d "$work"
  install -D -m 0755 "$work/$1" "$dest/$1"
}

fetch terraform "https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/terraform_${TERRAFORM_VERSION}_linux_${arch}.zip"
fetch tflint "https://github.com/terraform-linters/tflint/releases/download/v${TFLINT_VERSION}/tflint_linux_${arch}.zip"
"$dest/terraform" version | head -1
"$dest/tflint" --version | head -1
