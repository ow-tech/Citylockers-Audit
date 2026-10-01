#!/usr/bin/env bash
set -euo pipefail
umask 077

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib-backup.sh"
daily_dir=${AUDIT_BACKUP_DIR:-/var/backups/citylockers-audit/daily}
weekly_dir=${AUDIT_BACKUP_WEEKLY_DIR:-/var/backups/citylockers-audit/weekly}
retention=${AUDIT_BACKUP_WEEKLY_RETENTION:-12}
require_positive_integer AUDIT_BACKUP_WEEKLY_RETENTION "$retention"
[[ -n ${AUDIT_BACKUP_AGE_RECIPIENT:-} ]] || fail "AUDIT_BACKUP_AGE_RECIPIENT is required"
command -v age >/dev/null 2>&1 || fail "age is required; install it before encrypted backups can run"
mkdir -p -- "$weekly_dir"
chmod 700 "$weekly_dir"
mapfile -t daily_dumps < <(find "$daily_dir" -maxdepth 1 -type f -name 'citylockers-audit-*.dump' -printf '%f\n' | LC_ALL=C sort -r)
(( ${#daily_dumps[@]} > 0 )) || fail "no successful daily dump is available"
source_dump=
for candidate in "${daily_dumps[@]}"; do
  candidate_path="$daily_dir/$candidate"
  if [[ -f "$(checksum_file "$candidate_path")" ]] && (cd -- "$daily_dir" && sha256sum --check --status "$(basename -- "$(checksum_file "$candidate_path")")"); then
    source_dump=$candidate_path
    break
  fi
done
[[ -n $source_dump ]] || fail "no checksum-verified daily dump is available"
verify_checksum "$source_dump"
encrypted="$weekly_dir/$(basename -- "$source_dump").age"
tmp=$(mktemp "$weekly_dir/.$(basename -- "$encrypted").partial.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT
age --encrypt --recipient "$AUDIT_BACKUP_AGE_RECIPIENT" --output "$tmp" "$source_dump"
[[ -s $tmp ]] || fail "age produced an empty encrypted backup"
chmod 600 "$tmp"
mv -- "$tmp" "$encrypted"
trap - EXIT
write_checksum "$encrypted"

if [[ -n ${AUDIT_BACKUP_REMOTE_SCRIPT:-} ]]; then
  [[ -x $AUDIT_BACKUP_REMOTE_SCRIPT ]] || fail "AUDIT_BACKUP_REMOTE_SCRIPT is not executable"
  "$AUDIT_BACKUP_REMOTE_SCRIPT" "$encrypted"
fi
prune_artifacts "$weekly_dir" dump.age "$retention"
printf 'Encrypted weekly backup created: %s\n' "$encrypted"
