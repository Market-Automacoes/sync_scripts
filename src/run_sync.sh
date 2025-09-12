#!/usr/bin/env bash
set -euo pipefail

# Diretório deste arquivo (agora em Sync_Scrips/src)
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# (opcional) ativa venv: prioriza .venv na raiz do projeto; fallback para .venv dentro de src
if [ -f "$PROJ_ROOT/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$PROJ_ROOT/.venv/bin/activate"
elif [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/.venv/bin/activate"
fi

# Python (permite sobrescrever via env var PYTHON=/caminho/do/python)
PYTHON="${PYTHON:-python3}"

restore_on_error() {
  echo "[ERR] falha detectada — restaurando backups, se houver..."
  "$PYTHON" "$SCRIPT_DIR/restore_backups.py" || true
}
trap restore_on_error ERR INT

# 1) Sincroniza SVN
"$PYTHON" "$SCRIPT_DIR/sync_svn.py" "$@"

# 2) Preprocessa gestor.sql/supervisor.sql (gera cabeçalho, separadores, ANSI, sidecar)
"$PYTHON" "$SCRIPT_DIR/preprocess_sql.py"

# 3) Aplica updates nas bases (usa arquivos em ANSI/cp1252)
"$PYTHON" "$SCRIPT_DIR/apply_db_updates.py"

# 4) Gera arquivo numerado em Scripts/<Sistema>, faz svn add/commit e limpa fontes/backup
"$PYTHON" "$SCRIPT_DIR/post_sync_sql.py"
