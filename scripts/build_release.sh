#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="${1:-1.2.0-local-auth}"
release_dir="${project_dir}/dist"
archive="${release_dir}/afribounty-${version}.zip"

cd "${project_dir}"
mkdir -p "${release_dir}"
rm -f "${archive}" "${archive}.sha256"

python manage.py makemigrations --check --dry-run
python manage.py test tests -v 1
python -m compileall -q apps config tests tools
ruff check .
ruff format --check .
pip-audit -r requirements.lock
python tools/verify_zip08.py

staging_dir="$(mktemp -d)"
cleanup() { rm -rf "${staging_dir}"; }
trap cleanup EXIT

mkdir -p "${staging_dir}/afribounty-${version}"
cp -a . "${staging_dir}/afribounty-${version}/"
rm -rf "${staging_dir}/afribounty-${version}/.git" \
  "${staging_dir}/afribounty-${version}/.venv" \
  "${staging_dir}/afribounty-${version}/.ruff_cache" \
  "${staging_dir}/afribounty-${version}/dist" \
  "${staging_dir}/afribounty-${version}/__pycache__"
find "${staging_dir}/afribounty-${version}" -type d -name '__pycache__' -prune -exec rm -rf {} +
find "${staging_dir}/afribounty-${version}" -type f \( -name '*.pyc' -o -name '*.sqlite3' -o -name '*.db' -o -name '*.zip' -o -name '.env' -o -name '.env.production' \) -delete

(
  cd "${staging_dir}"
  zip -qr "${archive}" "afribounty-${version}"
)
unzip -t "${archive}" >/dev/null
sha256sum "${archive}" > "${archive}.sha256"
printf 'Release créée : %s\nChecksum : %s\n' "${archive}" "${archive}.sha256"
