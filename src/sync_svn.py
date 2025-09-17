#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Sincroniza a working copy SVN em src/Scripts a partir da URL configurada (HTTPS suportado).

- Estrutura do projeto:
    <raiz>/
      ├─ config.ini
      ├─ gestor.sql / supervisor.sql
      └─ src/
         ├─ Scripts/                (WC do SVN fica aqui)
         ├─ .svnconfig_noproxy/     (config local do SVN)
         └─ *.py

- Configuração:
  * URL:
      - Variável de ambiente: SVN_URL
      - ou seção [svn] no config.ini: url = https://...
  * Credenciais (se exigidas pelo servidor):
      - Variáveis de ambiente: SVN_USERNAME / SVN_PASSWORD
      - ou seção [auth] no config.ini: svn_username / svn_password
"""

import os
import sys
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from configparser import ConfigParser

# === Caminhos (estrutura nova) ===
THIS_DIR     = Path(__file__).resolve().parent        # src/
PROJECT_ROOT = THIS_DIR.parent                        # raiz do projeto
SCRIPTS_DIR  = THIS_DIR / "Scripts"                   # src/Scripts (WC do SVN)
CONFIG_PATH  = PROJECT_ROOT / "config.ini"            # config.ini na raiz
SVN_CFG_DIR  = THIS_DIR / ".svnconfig_noproxy"        # config svn local (anti-proxy)

# --------------------------------------------------------------------
# Utilidades básicas
# --------------------------------------------------------------------
def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None

def run(cmd, cwd=None, env=None, check=True, capture=False):
    """Executa comando e retorna CompletedProcess; imprime linha de comando."""
    print("+", " ".join(map(str, cmd)))
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        env=env,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )
    if capture and result.stdout:
        print(result.stdout, end="")
    if check and result.returncode != 0:
        sys.exit(result.returncode)
    return result

def is_working_copy(path: Path) -> bool:
    return (path / ".svn").is_dir()

def ensure_svn_installed():
    if not have("svn"):
        print("Erro: o cliente 'svn' não está instalado ou não está no PATH.", file=sys.stderr)
        print("Instale o Subversion e tente novamente. Ex.:", file=sys.stderr)
        print("  macOS:  brew install subversion", file=sys.stderr)
        print("  Ubuntu: sudo apt-get install subversion", file=sys.stderr)
        sys.exit(1)

# --------------------------------------------------------------------
# Carregar config
# --------------------------------------------------------------------
def load_config():
    cfg = ConfigParser()
    if CONFIG_PATH.exists():
        try:
            cfg.read(CONFIG_PATH, encoding="utf-8")
        except Exception:
            cfg.read(CONFIG_PATH, encoding="latin-1")
    return cfg

def get_svn_settings():
    """
    Coleta URL e credenciais do ambiente e/ou config.ini.
    - URL é obrigatória: env(SVN_URL) ou [svn] url no config.ini.
    - Credenciais são opcionais (caso o servidor aceite anônimo).
    """
    cfg = load_config()

    url = os.environ.get("SVN_URL") or cfg.get("svn", "url", fallback="").strip()
    if not url:
        print("ERRO: Não foi possível determinar a URL do repositório SVN.", file=sys.stderr)
        print("Defina a variável de ambiente SVN_URL ou adicione no config.ini:", file=sys.stderr)
        print("[svn]\nurl = https://servidor/svn/repo/Scripts", file=sys.stderr)
        sys.exit(2)

    username = os.environ.get("SVN_USERNAME") or cfg.get("auth", "svn_username", fallback="").strip()
    password = os.environ.get("SVN_PASSWORD") or cfg.get("auth", "svn_password", fallback="").strip()

    return url, username, password

# --------------------------------------------------------------------
# Config SVN local e ambiente sem proxy
# --------------------------------------------------------------------
def make_no_proxy_config_dir() -> Path:
    """
    Cria um diretório de configuração para o SVN com exceções de proxy,
    útil para redes locais.
    """
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
    """
    Remove variáveis de proxy do ambiente para evitar que o svn tente usar proxy em rede local.
    """
    env = os.environ.copy()
    for k in ("http_proxy","https_proxy","HTTP_PROXY","HTTPS_PROXY",
              "all_proxy","ALL_PROXY","no_proxy","NO_PROXY"):
        env.pop(k, None)
    return env

def svn_common_opts(username: str, password: str, cfg_dir: Path):
    """
    Opções comuns. Inclui flags para confiar em certificado self-signed em modo
    não interativo (evita prompts quando o servidor usa HTTPS com cert. próprio).
    """
    opts = [
        "--non-interactive",
        "--config-dir", str(cfg_dir),
        # Confiar no certificado em modo não interativo:
        "--trust-server-cert",
        "--trust-server-cert-failures",
        "unknown-ca,cn-mismatch,expired,not-yet-valid,other",
    ]
    if username:
        opts += ["--username", username]
    if password:
        # --no-auth-cache evita gravar a senha no disco; remova se quiser cachear
        opts += ["--password", password, "--no-auth-cache"]
    return opts

# --------------------------------------------------------------------
# Relocation automático (HTTP -> HTTPS, ou mudança de host/caminho)
# --------------------------------------------------------------------
def get_wc_url(dest: Path) -> str | None:
    """Retorna a URL atual da working copy (ou None se não for WC)."""
    if not is_working_copy(dest):
        return None
    try:
        res = subprocess.run(
            ["svn", "info", "--show-item", "url"],
            cwd=dest,
            text=True,
            capture_output=True,
            check=True,
        )
        url = (res.stdout or "").strip()
        return url or None
    except Exception:
        return None

def relocate_wc(current_url: str, new_url: str, dest: Path, username: str, password: str, cfg_dir: Path, env: dict):
    """Tenta relocar WC para a nova URL (svn relocate; fallback switch --relocate)."""
    opts = svn_common_opts(username, password, cfg_dir)
    print(f"Aviso: WC aponta para {current_url}. Realocando para {new_url}...")
    # Primeiro tenta 'svn relocate' (Subversion recente)
    try:
        run(["svn", "relocate", current_url, new_url, *opts], cwd=dest, env=env, check=True)
        return
    except SystemExit:
        # Se falhar (ou versão antiga), tenta via 'svn switch --relocate'
        run(["svn", "switch", "--relocate", current_url, new_url, *opts], cwd=dest, env=env, check=True)

# --------------------------------------------------------------------
# Checkout/Update com auto-relocate
# --------------------------------------------------------------------
def checkout_or_update(repo_url: str, dest: Path, username: str, password: str, cfg_dir: Path, env: dict):
    if dest.exists() and not is_working_copy(dest):
        # Evita sobrescrever uma pasta qualquer chamada "Scripts" que não seja WC
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = dest.parent / f"{dest.name}.backup-{stamp}"
        print(f"Aviso: '{dest}' existe mas não é uma working copy SVN.")
        print(f"Movendo para backup: {backup}")
        dest.rename(backup)

    opts = svn_common_opts(username, password, cfg_dir)

    if is_working_copy(dest):
        # Se a URL atual for diferente da desejada (ex.: http -> https), faz relocate automático
        wc_url = get_wc_url(dest)
        if wc_url and wc_url != repo_url:
            relocate_wc(wc_url, repo_url, dest, username, password, cfg_dir, env)

        # Atualiza WC
        run(["svn", "cleanup", *opts, str(dest)], env=env)
        run(["svn", "update",  *opts, str(dest)], env=env)
    else:
        # Checkout inicial
        dest.parent.mkdir(parents=True, exist_ok=True)
        run(["svn", "checkout", *opts, repo_url, str(dest)], env=env)

# --------------------------------------------------------------------
# Main
# --------------------------------------------------------------------
def main():
    ensure_svn_installed()
    url, user, pw = get_svn_settings()
    cfg_dir = make_no_proxy_config_dir()
    env = clean_proxy_env()

    print(f"Sincronizando SVN '{url}' -> '{SCRIPTS_DIR}'")
    checkout_or_update(url, SCRIPTS_DIR, user, pw, cfg_dir, env)
    print("✅ Pronto! Pasta sincronizada.")

if __name__ == "__main__":
    main()
