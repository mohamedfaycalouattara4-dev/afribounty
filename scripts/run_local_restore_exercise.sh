#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage : $0 <base_sqlite_source> <repertoire_exercice>" >&2
  exit 64
fi

source_db="$1"
exercise_dir="$2"
project_dir="$(cd "$(dirname "$0")/.." && pwd)"
snapshot_db="$exercise_dir/source-snapshot.sqlite3"
restored_db="$exercise_dir/restored.sqlite3"

if [ ! -f "$source_db" ]; then
  echo "Base SQLite source introuvable : $source_db" >&2
  exit 66
fi

if [ -e "$exercise_dir" ]; then
  echo "Le répertoire d’exercice existe déjà : $exercise_dir" >&2
  exit 73
fi

started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mkdir -p "$exercise_dir"
cp "$source_db" "$snapshot_db"
sha256sum "$snapshot_db" > "$exercise_dir/source-snapshot.sha256"

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.development}"
export IDENTITY_TOTP_FERNET_KEY="${IDENTITY_TOTP_FERNET_KEY:?IDENTITY_TOTP_FERNET_KEY est obligatoire}"

cd "$project_dir"
DJANGO_DATABASE_URL="sqlite:///$snapshot_db" python3 manage.py restore_exercise_metrics > "$exercise_dir/source-metrics.json"

cp "$snapshot_db" "$restored_db"
restore_started_epoch="$(date +%s)"
DJANGO_DATABASE_URL="sqlite:///$restored_db" python3 manage.py migrate --noinput
DJANGO_DATABASE_URL="sqlite:///$restored_db" python3 manage.py verify_audit_integrity --strict
DJANGO_DATABASE_URL="sqlite:///$restored_db" python3 manage.py restore_exercise_metrics > "$exercise_dir/restored-metrics.json"
cmp --silent "$exercise_dir/source-metrics.json" "$exercise_dir/restored-metrics.json"
sha256sum "$restored_db" > "$exercise_dir/restored.sqlite3.sha256"
restore_completed_epoch="$(date +%s)"

cat > "$exercise_dir/RESULT.md" <<EOF
# Résultat d’exercice de restauration local

| Élément | Valeur |
| --- | --- |
| Début UTC | $started_at |
| Base source | $(basename "$source_db") |
| Empreinte de l’instantané | $(cut -d' ' -f1 "$exercise_dir/source-snapshot.sha256") |
| Empreinte de la base restaurée | $(cut -d' ' -f1 "$exercise_dir/restored.sqlite3.sha256") |
| Durée de restauration observée | $((restore_completed_epoch - restore_started_epoch)) secondes |
| Migrations | Appliquées sans erreur |
| Intégrité HMAC d’audit | Vérifiée strictement |
| Compteurs non sensibles | Identiques entre source et restauration |

> Cet exercice est local et isolé. Il ne constitue ni une sauvegarde de production, ni une preuve de RPO/RTO de production, ni une validation d’un fournisseur externe.
EOF

echo "Exercice de restauration local réussi : $exercise_dir"
