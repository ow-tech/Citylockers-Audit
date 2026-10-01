#!/usr/bin/env bash
# Shared, deliberately small helpers for operator-run backup scripts.
set -euo pipefail

audit_script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
audit_repo_dir=$(cd -- "$audit_script_dir/.." && pwd)
AUDIT_COMPOSE_FILE=${AUDIT_COMPOSE_FILE:-"$audit_repo_dir/docker-compose.yml"}
AUDIT_POSTGRES_SERVICE=${AUDIT_POSTGRES_SERVICE:-postgres}

fail() { printf '%s\n' "citylockers-audit backup: $*" >&2; exit 1; }

compose() {
  if [[ -n ${AUDIT_COMPOSE_PROJECT_NAME:-} ]]; then
    docker compose --project-name "$AUDIT_COMPOSE_PROJECT_NAME" -f "$AUDIT_COMPOSE_FILE" "$@"
  else
    docker compose -f "$AUDIT_COMPOSE_FILE" "$@"
  fi
}

require_positive_integer() {
  [[ $2 =~ ^[1-9][0-9]*$ ]] || fail "$1 must be a positive integer"
}

checksum_file() { printf '%s.sha256' "$1"; }

write_checksum() {
  local artifact=$1 checksum
  checksum=$(sha256sum "$artifact")
  printf '%s\n' "$checksum" > "$(checksum_file "$artifact")"
  chmod 600 "$(checksum_file "$artifact")"
}

verify_checksum() {
  local artifact=$1 checksum
  checksum=$(checksum_file "$artifact")
  [[ -f $checksum ]] || fail "checksum is required for $artifact"
  (cd -- "$(dirname -- "$artifact")" && sha256sum --check --status "$(basename -- "$checksum")") || fail "checksum verification failed for $artifact"
}

prune_artifacts() {
  local directory=$1 suffix=$2 retention=$3
  local -a artifacts=()
  require_positive_integer retention "$retention"
  mapfile -t artifacts < <(find "$directory" -maxdepth 1 -type f -name "citylockers-audit-*.${suffix}" -printf '%f\n' | LC_ALL=C sort -r)
  local index
  for ((index=retention; index<${#artifacts[@]}; index++)); do
    rm -f -- "$directory/${artifacts[index]}" "$directory/${artifacts[index]}.sha256" "$directory/${artifacts[index]%.dump}.metadata"
  done
}
