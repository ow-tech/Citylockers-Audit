#!/usr/bin/env bash
set -euo pipefail
umask 077

source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/lib-backup.sh"

backup_dir=${AUDIT_BACKUP_DIR:-/var/backups/citylockers-audit/daily}
retention=${AUDIT_BACKUP_DAILY_RETENTION:-14}
require_positive_integer AUDIT_BACKUP_DAILY_RETENTION "$retention"
mkdir -p -- "$backup_dir"
chmod 700 "$backup_dir"
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
filename="citylockers-audit-${timestamp}.dump"
target="$backup_dir/$filename"
[[ ! -e $target ]] || fail "a backup already exists for this UTC second; retry rather than overwrite it"
tmp=$(mktemp "$backup_dir/.${filename}.partial.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT

# The postgres image receives credentials through Compose's protected environment; none are echoed here.
compose exec -T "$AUDIT_POSTGRES_SERVICE" sh -ec 'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$tmp"
[[ -s $tmp ]] || fail "pg_dump produced an empty backup"
chmod 600 "$tmp"
mv -- "$tmp" "$target"
trap - EXIT
write_checksum "$target"

migration_version=$(compose exec -T "$AUDIT_POSTGRES_SERVICE" sh -ec 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atqc "SELECT coalesce(max(version), '\''none'\'') FROM audit.schema_migrations"' | tr -d '\r\n')
dump_size=$(wc -c < "$target" | tr -d ' ')
dump_hash=$(awk '{print $1}' "$(checksum_file "$target")")
metadata_tmp=$(mktemp "$backup_dir/.${filename}.metadata.partial.XXXXXX")
{
  printf 'generated_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'database_logical_name=%s\n' "${AUDIT_POSTGRES_DB:-audit}"
  printf 'application_version=%s\n' "${AUDIT_VERSION:-unknown}"
  printf 'commit_sha=%s\n' "${AUDIT_COMMIT_SHA:-unknown}"
  printf 'schema_migration_version=%s\n' "$migration_version"
  printf 'dump_filename=%s\n' "$filename"
  printf 'dump_size_bytes=%s\n' "$dump_size"
  printf 'sha256=%s\n' "$dump_hash"
} > "$metadata_tmp"
chmod 600 "$metadata_tmp"
mv -- "$metadata_tmp" "$backup_dir/${filename%.dump}.metadata"

# Pruning happens only after the new dump, checksum, and metadata are all durable.
prune_artifacts "$backup_dir" dump "$retention"
printf 'Backup created: %s (%s bytes)\n' "$target" "$dump_size"
