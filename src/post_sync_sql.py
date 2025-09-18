#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gera os arquivos numerados em src/Scripts/(Gestor|Supervisor),
faz svn add/commit (se a pasta for working copy) e integra com o
backup criado pelo preprocess_sql.py.

Estrutura esperada:
<raiz>/
  ├─ config.ini
  ├─ gestor.sql / supervisor.sql     (arquivos de entrada)
  └─ src/
     ├─ Scripts/                     (WC do SVN aqui)
     │  ├─ Gestor/
     │  └─ Supervisor/
     ├─ .preprocess_backup/          (backups do preprocess)
     │  └─ pending.txt
     ├─ .svnconfig_noproxy/          (config local de svn)
     └─ *.py
"""

import re
import os
import sys
import subprocess
from pathlib import Path
from configparser import ConfigParser
from datetime import datetime

# === Caminhos (nova estrutura) ===
THIS_DIR      = Path(__file__).resolve().parent       # src/
PROJECT_ROOT  = THIS_DIR.parent                       # raiz do projeto
SCRIPTS_DIR   = THIS_DIR / "Scripts"                  # src/Scripts
GESTOR_DIR    = SCRIPTS_DIR / "Gestor"
SUPERV_DIR    = SCRIPTS_DIR / "Supervisor"
CONFIG_PATH   = PROJECT_ROOT / "config.ini"           # config.ini na raiz

# Backups gerenciados pelo preprocess_sql.py
BACKUP_DIR    = THIS_DIR / ".preprocess_backup"
PENDING_FILE  = BACKUP_DIR / "pending.txt"

# Config svn local (anti-proxy)
SVN_CFG_DIR   = THIS_DIR / ".svnconfig_noproxy"

# Fontes na RAIZ do projeto
GESTOR_SRC_PATH     = PROJECT_ROOT / "gestor.sql"
SUPERVISOR_SRC_PATH = PROJECT_ROOT / "supervisor.sql"

CREATED_FILES: list[Path] = []  # coletar criados para mensagem de commit

# ======================== BACKUP HELPERS ========================

def _clean_cstyle_header_markers(content_bytes: bytes) -> bytes:
    """
    Remove apenas os marcadores C-style '/*' e '*/' do CABEÇALHO,
    mantendo as linhas que começam com '--#...'.
    Não mexe no restante do arquivo.
    """
    # tenta cp1252 primeiro (mantém ANSI), depois fallbacks só pra leitura
    for enc in ("cp1252", "utf-8", "latin-1"):
        try:
            text = content_bytes.decode(enc)
            read_enc = enc
            break
        except UnicodeDecodeError:
            continue
    else:
        # último recurso
        text = content_bytes.decode("utf-8", errors="replace")
        read_enc = "utf-8"

    # Delimita o cabeçalho até a 1ª chamada de fn_verifica_script (para não
    # remover '/* ... */' que por acaso exista em outras partes do script)
    mark = re.search(r"fn_verifica_script\s*\(", text, flags=re.IGNORECASE)
    if mark:
        head = text[:mark.start()]
        tail = text[mark.start():]
    else:
        # se não achar, considera arquivo todo como "head" por segurança mínima
        head, tail = text, ""

    # No cabeçalho, trocamos somente os marcadores '/*' e '*/' por espaço
    # (evita que Python/psql entendam como bloco de comentário estranho)
    head_clean = head.replace("/*", " ").replace("*/", " ")

    cleaned = head_clean + tail
    # volta para cp1252 para preservar o padrão ANSI (com substituição se precisar)
    return cleaned.encode("cp1252", errors="replace")


def _load_pending_entries():
    """
    Lê o pending.txt no formato 'orig_abs_path|backup_abs_path' por linha.
    Retorna lista de tuplas (Path(orig), Path(backup)).
    """
    if not PENDING_FILE.exists():
        return []
    lines = PENDING_FILE.read_text(encoding="utf-8").splitlines()
    out = []
    for ln in lines:
        if "|" not in ln:
            continue
        left, right = ln.split("|", 1)
        out.append((Path(left), Path(right)))
    return out

def _save_pending_entries(entries):
    if not entries:
        # limpar tudo
        try:
            if PENDING_FILE.exists():
                PENDING_FILE.unlink()
            if BACKUP_DIR.exists() and not any(BACKUP_DIR.iterdir()):
                BACKUP_DIR.rmdir()
        except Exception:
            pass
        return
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    txt = "\n".join(f"{orig.resolve()}|{bkp.resolve()}" for (orig, bkp) in entries) + "\n"
    PENDING_FILE.write_text(txt, encoding="utf-8")

def clear_backup_record(orig: Path):
    """
    Remove do pending.txt o registro do arquivo 'orig' e apaga o .bak associado.
    Se não houver registro, não faz nada.
    """
    entries = _load_pending_entries()
    kept = []
    removed = False
    for (o, b) in entries:
        if o.resolve() == orig.resolve():
            # apaga o backup
            try:
                if b.exists():
                    b.unlink()
            except Exception:
                pass
            removed = True
        else:
            kept.append((o, b))
    _save_pending_entries(kept)
    if removed:
        print(f"[backup] limpo registro de {orig.name}")

def restore_backup(orig: Path):
    """
    Restaura o arquivo 'orig' a partir do backup, se existir no pending.txt.
    Após restaurar, remove o registro e o .bak.
    """
    entries = _load_pending_entries()
    kept = []
    restored = False
    for (o, b) in entries:
        if o.resolve() == orig.resolve():
            try:
                if b.exists():
                    if orig.exists():
                        orig.unlink()
                    os.replace(str(b), str(orig))
                    restored = True
                    print(f"[restore] {orig.name} restaurado a partir de {b.name}")
            except Exception as e:
                print(f"[restore][warn] falha ao restaurar {orig}: {e}", file=sys.stderr)
        else:
            kept.append((o, b))
    _save_pending_entries(kept)
    return restored

# ======================== CONFIG & SVN ==========================

def load_config():
    cfg = ConfigParser()
    if CONFIG_PATH.exists():
        try:
            cfg.read(CONFIG_PATH, encoding="utf-8")
        except Exception:
            cfg.read(CONFIG_PATH, encoding="latin-1")
    else:
        print(f"Aviso: {CONFIG_PATH} não encontrado. Usando variáveis de ambiente (se houver).")

    username = (os.environ.get("SVN_USERNAME")
                or cfg.get("auth", "svn_username", fallback=""))
    password = (os.environ.get("SVN_PASSWORD")
                or cfg.get("auth", "svn_password", fallback=""))
    initials = (os.environ.get("USER_INITIALS")
                or cfg.get("user", "initials", fallback="")).upper()

    if not re.fullmatch(r"[A-Za-z]{2}", initials or ""):
        print("Erro: as iniciais devem ter exatamente 2 letras (ex.: JO).", file=sys.stderr)
        sys.exit(2)

    return username, password, initials

def ensure_dirs():
    GESTOR_DIR.mkdir(parents=True, exist_ok=True)
    SUPERV_DIR.mkdir(parents=True, exist_ok=True)

def is_wc(path: Path) -> bool:
    # Consideramos a raiz da WC como src/Scripts/
    return (SCRIPTS_DIR / ".svn").is_dir()

# ---------- BLOCO ANTI-PROXY ----------
def make_no_proxy_config_dir() -> Path:
    servers = SVN_CFG_DIR / "servers"
    if not servers.exists():
        SVN_CFG_DIR.mkdir(parents=True, exist_ok=True)
        servers.write_text(
            "[global]\n"
            "http-proxy-exceptions = 192.168.*, 10.*, 172.16.*, localhost, 127.*, ::1\n",
            encoding="utf-8",
        )
    return SVN_CFG_DIR

def clean_proxy_env() -> dict:
    env = os.environ.copy()
    for k in ("http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY",
              "all_proxy","ALL_PROXY","no_proxy","NO_PROXY"):
        env.pop(k, None)
    return env
# --------------------------------------

def run(cmd, cwd=None, check=True, capture=False, env=None):
    print("+", " ".join(cmd))
    res = subprocess.run(
        cmd, cwd=cwd, text=True, env=env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None
    )
    if capture and res.stdout:
        print(res.stdout, end="")
    if check and res.returncode != 0:
        sys.exit(res.returncode)
    return res

def svn_opts_base(username: str, password: str, cfg_dir: Path):
    """
    Opções globais do SVN, incluindo confiança no certificado HTTPS em modo
    não interativo (autoassinado, CN diferente, expirado, etc.).
    """
    opts = [
        "--non-interactive",
        "--config-dir", str(cfg_dir),
        "--trust-server-cert",
        "--trust-server-cert-failures", "unknown-ca,cn-mismatch,expired,not-yet-valid,other",
    ]
    if username:
        opts += ["--username", username]
    if password:
        opts += ["--password", password, "--no-auth-cache"]
    return opts

def next_seq_for(folder: Path, letter: str) -> int:
    """
    Arquivos no formato: NNNN.0.<letter><XX>.sql
    Ex.: 9341.0.GJO.sql  -> letter='G'
    """
    pat = re.compile(rf"^(\d{{4}})\.0\.{letter}[A-Za-z]{{2}}\.sql$")
    max_n = 0
    if folder.exists():
        for name in os.listdir(folder):
            m = pat.match(name)
            if m:
                n = int(m.group(1))
                if n > max_n:
                    max_n = n
    return max_n + 1

def write_file_bytes(dest_folder: Path, letter: str, initials: str, content_bytes: bytes) -> Path:
    seq = next_seq_for(dest_folder, letter)
    fname = f"{seq:04d}.0.{letter}{initials}.sql"
    out_path = dest_folder / fname
    out_path.write_bytes(content_bytes)  # preserva a codificação original (ANSI cp1252)
    try:
        rel = out_path.relative_to(PROJECT_ROOT)
    except Exception:
        rel = out_path
    print(f"✅ Criado: {rel}")
    CREATED_FILES.append(out_path)
    return out_path

def svn_add_if_wc(path: Path, username: str, password: str, cfg_dir: Path, env: dict):
    if is_wc(SCRIPTS_DIR):
        # Rodamos dentro de src/Scripts/ para que os caminhos fiquem relativos
        rel = path.relative_to(SCRIPTS_DIR)
        run(["svn", "add", "--force", str(rel), *svn_opts_base(username, password, cfg_dir)],
            cwd=SCRIPTS_DIR, check=False, env=env)

def svn_commit_if_changes(username: str, password: str, cfg_dir: Path, env: dict) -> bool:
    """
    Tenta commitar alterações na WC.
    Retorna True se houve commit, False se não era WC ou não havia mudanças.
    """
    if not is_wc(SCRIPTS_DIR):
        print("ℹ️ Pasta src/Scripts não é uma working copy SVN. Pulando commit.")
        return False

    # Usa as mesmas opções (com confiança de certificado) também no status.
    st = subprocess.run(
        ["svn", "status", *svn_opts_base(username, password, cfg_dir)],
        cwd=SCRIPTS_DIR, text=True, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    changes = [ln for ln in (st.stdout or "").splitlines() if ln[:1] in {"A", "M", "D", "R", "!"}]
    if not changes:
        print("ℹ️ Nenhuma alteração para commitar.")
        return False

    when = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if CREATED_FILES:
        nomes = ", ".join(p.name for p in CREATED_FILES)
        msg = f"auto: adiciona {nomes} ({when})"
    else:
        msg = f"auto: pós-sync ({when})"

    run(["svn", "commit", "-m", msg, *svn_opts_base(username, password, cfg_dir)],
        cwd=SCRIPTS_DIR, env=env, check=True, capture=True)
    return True

def delete_sources(paths):
    for p in paths:
        try:
            if p.exists():
                p.unlink()
                print(f"🗑️ Removido: {p.name}")
        except Exception as e:
            # Não derruba o processo por falha na limpeza
            print(f"⚠️ Não foi possível remover {p.name}: {e}")

# ============================== MAIN ==============================

def process_role(src_path: Path, dest_folder: Path, letter: str, initials: str,
                 username: str, password: str, cfg_dir: Path, env: dict):
    if not src_path.exists():
        return  # nada a fazer

    # LEITURA EM BINÁRIO para preservar ANSI (cp1252)
    content_bytes = src_path.read_bytes()

    # LIMPA APENAS OS MARCADORES C-STYLE DO CABEÇALHO 
    content_bytes = _clean_cstyle_header_markers(content_bytes)

    created = write_file_bytes(dest_folder, letter, initials, content_bytes)
    svn_add_if_wc(created, username, password, cfg_dir, env)

def main():
    username, password, initials = load_config()
    ensure_dirs()

    cfg_dir = make_no_proxy_config_dir()
    env = clean_proxy_env()

    # Registra fontes existentes na RAIZ para decidir o que fazer no final
    root_sources = []
    if GESTOR_SRC_PATH.exists(): root_sources.append(GESTOR_SRC_PATH)
    if SUPERVISOR_SRC_PATH.exists(): root_sources.append(SUPERVISOR_SRC_PATH)

    # Cria arquivos numerados (se houver fontes)
    process_role(GESTOR_SRC_PATH,     GESTOR_DIR, "G", initials, username, password, cfg_dir, env)
    process_role(SUPERVISOR_SRC_PATH, SUPERV_DIR, "S", initials, username, password, cfg_dir, env)

    # Tenta o commit
    committed = svn_commit_if_changes(username, password, cfg_dir, env)

    if committed:
        # Sucesso: apagar fontes da raiz E limpar backups
        delete_sources(root_sources)
        for src in root_sources:
            clear_backup_record(src)
    else:
        # Não comitou (não era WC ou não havia mudanças): restaura fontes originais da raiz
        for src in root_sources:
            restored = restore_backup(src)
            if not restored:
                print(f"[restore] nenhum backup pendente para {src.name}.")

    print("🏁 pós-sync finalizado.")

if __name__ == "__main__":
    main()
