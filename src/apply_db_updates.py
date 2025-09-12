#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Aplica atualizações nas bases PostgreSQL antes de enviar o script ao SVN.

Estrutura do projeto:
<raiz>/
  ├─ config.ini
  ├─ gestor.sql / supervisor.sql          (arquivos tratados pelo preprocess)
  └─ src/
     ├─ .target_gestor.txt / .target_supervisor.txt
     ├─ Scripts/
     │  ├─ Gestor/                        (scripts versionados)
     │  └─ Supervisor/
     └─ apply_db_updates.py               (este arquivo)

Fluxo por sistema presente (gestor.sql e/ou supervisor.sql):
 1) Traz TEST e DEV até a última versão disponível em Scripts/<Sistema> (aplica pendentes).
 2) Executa o NOVO script tratado completo em TEST.
 3) Executa apenas: select * from sistema.fn_atualiza_script('<NOME>') em DEV (sem “.sql”).

Sai com código != 0 se algo falhar.
"""

import os
import re
import sys
from pathlib import Path
from configparser import ConfigParser

# =================== Constantes / caminhos ===================

END_MARK = "---------- END OFF COMMAND ----------"

THIS_DIR     = Path(__file__).resolve().parent        # src/
PROJECT_ROOT = THIS_DIR.parent                        # raiz
SCRIPTS_DIR  = THIS_DIR / "Scripts"                   # src/Scripts
GESTOR_DIR   = SCRIPTS_DIR / "Gestor"
SUPERV_DIR   = SCRIPTS_DIR / "Supervisor"
CONFIG_PATH  = PROJECT_ROOT / "config.ini"            # config.ini na raiz

TARGETS = [
    {
        "system":   "gestor",
        "src_path": PROJECT_ROOT / "gestor.sql",
        "sidecar":  THIS_DIR / ".target_gestor.txt",
        "base_dir": GESTOR_DIR,
    },
    {
        "system":   "supervisor",
        "src_path": PROJECT_ROOT / "supervisor.sql",
        "sidecar":  THIS_DIR / ".target_supervisor.txt",
        "base_dir": SUPERV_DIR,
    },
]

# =================== Utilidades ===================

def die(msg: str, code: int = 1):
    print(f"[ERRO] {msg}", file=sys.stderr)
    sys.exit(code)

def load_cfg() -> ConfigParser:
    if not CONFIG_PATH.exists():
        die("config.ini não encontrado na raiz do projeto.")
    cfg = ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg

def get_db_driver():
    """
    Prefere psycopg 3 (psycopg), cai para psycopg2 se necessário.
    Compatível com: python3 -m pip install "psycopg[binary]"
    """
    try:
        import psycopg as pg   # psycopg v3
        return pg, 3
    except Exception:
        try:
            import psycopg2 as pg  # fallback v2
            return pg, 2
        except Exception:
            die("Driver não encontrado. Instale: python3 -m pip install 'psycopg[binary]'")

def load_db_pair(cfg: ConfigParser, system: str):
    """
    Lê o par de conexões para um sistema: ('gestor'|'supervisor')
    Seções:
      gestor     -> db_test_gestor / db_dev_gestor
      supervisor -> db_test_supervisor / db_dev_supervisor
    Retorna tupla (dict_test, dict_dev).
    """
    sec_test = f"db_test_{system}"
    sec_dev  = f"db_dev_{system}"
    if sec_test not in cfg or sec_dev not in cfg:
        die(f"Seções [{sec_test}] e/ou [{sec_dev}] ausentes em config.ini")

    def read_section(sec: str) -> dict:
        s = cfg[sec]
        return dict(
            host=s.get("host", "").strip(),
            port=int(s.get("port", "5432")),
            dbname=s.get("dbname", "").strip(),
            user=s.get("user", "").strip(),
            password=s.get("password", "").strip(),
        )

    return read_section(sec_test), read_section(sec_dev)

def connect_db(pg, cfg: dict):
    try:
        conn = pg.connect(
            host=cfg["host"], port=cfg["port"],
            dbname=cfg["dbname"], user=cfg["user"], password=cfg["password"]
        )
        # psycopg3 e psycopg2: autocommit False por padrão; torna explícito:
        try:
            conn.autocommit = False
        except Exception:
            pass
        return conn
    except Exception as e:
        die(f"Falha ao conectar em {cfg['host']}:{cfg['port']}/{cfg['dbname']} - {e}")

SEQ_RE = re.compile(r'(\d{4})\.0\.[GS][A-Za-z]{2}')

def parse_seq_from_name(name: str) -> int:
    m = SEQ_RE.search(name)
    return int(m.group(1)) if m else 0

def get_last_applied_seq(conn):
    sql = """
    select nm_arquivo
      from sistema.tb_sys_controle_versao
     order by nr_versao_banco desc
     limit 1
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
            if not row or not row[0]:
                return 0, ""
            nm = str(row[0])
            return parse_seq_from_name(nm), nm
    except Exception as e:
        conn.rollback()
        die(f"Falha ao consultar controle de versão: {e}")

def list_repo_scripts_for_dir(base_dir: Path):
    """
    Lista scripts existentes no diretório (Gestor/Supervisor),
    padrão NNNN.0.[GS]XX.sql
    Retorna lista de tuplas (seq, path, name) ordenadas por seq.
    """
    pat = re.compile(r'^(\d{4})\.0\.[GS][A-Za-z]{2}\.sql$')
    items = []
    if base_dir.exists():
        for name in os.listdir(base_dir):
            m = pat.match(name)
            if m:
                seq = int(m.group(1))
                items.append((seq, base_dir / name, name))
    items.sort(key=lambda t: t[0])
    return items

def read_text_auto(path: Path) -> str:
    # Preferimos ANSI cp1252 (preprocess salva assim), com fallbacks
    for enc in ("cp1252", "utf-8", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")

def split_blocks_by_endmark(text: str):
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    if END_MARK in t:
        parts = [b.strip() for b in t.split(END_MARK)]
        return [p for p in parts if p]
    return [t.strip()] if t.strip() else []

def exec_blocks(conn, blocks, label: str):
    """
    Executa uma lista de blocos em uma única transação.
    Se qualquer bloco falhar, ROLLBACK e aborta.
    """
    try:
        with conn.cursor() as cur:
            for i, b in enumerate(blocks, 1):
                if not b.strip():
                    continue
                cur.execute(b)
        conn.commit()
        print(f"[OK] {label}: {len(blocks)} bloco(s) executado(s).")
    except Exception as e:
        conn.rollback()
        die(f"Falha executando {label}: {e}")

def apply_full_script_file(conn, file_path: Path):
    text = read_text_auto(file_path)
    blocks = split_blocks_by_endmark(text)
    exec_blocks(conn, blocks, f"{file_path.name}")

def apply_full_script_text(conn, text: str, label: str):
    blocks = split_blocks_by_endmark(text)
    exec_blocks(conn, blocks, label)

def apply_pending_repo_scripts(conn, base_dir: Path, sys_label: str):
    """
    Atualiza a base executando scripts pendentes do diretório correspondente.
    """
    current_seq, current_name = get_last_applied_seq(conn)
    repo = list_repo_scripts_for_dir(base_dir)
    pend = [item for item in repo if item[0] > current_seq]
    if not pend:
        print(f"[INFO] {sys_label}: Base já está em dia (último={current_name or 'nenhum'}).")
        return
    print(f"[INFO] {sys_label}: Executando {len(pend)} script(s) pendente(s) a partir de {current_seq}...")
    for seq, path, name in pend:
        apply_full_script_file(conn, path)

def load_new_targets():
    """
    Lê alvos gerados pelo preprocess:
      src/.target_gestor.txt     + <raiz>/gestor.sql
      src/.target_supervisor.txt + <raiz>/supervisor.sql
    Retorna lista: {system, target_name, content, base_dir}
    """
    results = []
    for t in TARGETS:
        side_path = t["sidecar"]
        src_path  = t["src_path"]
        if side_path.exists() and src_path.exists():
            target_name = side_path.read_text(encoding="utf-8").strip()
            # preprocess salva ANSI (cp1252)
            content = read_text_auto(src_path)
            results.append(dict(system=t["system"], target_name=target_name,
                                content=content, base_dir=t["base_dir"]))
    return results

# =================== Pipeline principal ===================

def process_for_system(pg, cfg: ConfigParser, system: str, target_name: str, content: str, base_dir: Path):
    # Lê par de conexões do sistema
    test_cfg, dev_cfg = load_db_pair(cfg, system)

    # Conecta
    test_conn = connect_db(pg, test_cfg)
    dev_conn  = connect_db(pg, dev_cfg)

    sys_label = system.upper()

    # 1) Trazer TEST e DEV até o último script do diretório do sistema
    print(f"[{sys_label}][TEST] Verificando e aplicando pendências...")
    apply_pending_repo_scripts(test_conn, base_dir, f"{sys_label}/TEST")

    print(f"[{sys_label}][DEV ] Verificando e aplicando pendências...")
    apply_pending_repo_scripts(dev_conn, base_dir, f"{sys_label}/DEV ")

    # 2) Executar NOVO script completo em TEST
    apply_full_script_text(test_conn, content, f"NOVO({target_name})@{sys_label}/TEST")

    # 3) Executar SOMENTE fn_atualiza_script('<NOME>') em DEV (sem .sql)
    script_id = re.sub(r'\.sql$', '', target_name, flags=re.IGNORECASE)
    stmt = f"select * from sistema.fn_atualiza_script('{script_id}');"
    try:
        with dev_conn.cursor() as cur:
            cur.execute(stmt)
        dev_conn.commit()
        print(f"[OK] {sys_label}/DEV: {script_id} marcado via fn_atualiza_script.")
    except Exception as e:
        dev_conn.rollback()
        die(f"{sys_label}/DEV falhou ao atualizar {script_id} via fn_atualiza_script: {e}")

    # Fecha conexões
    test_conn.close()
    dev_conn.close()

def main():
    cfg = load_cfg()
    pg, ver = get_db_driver()
    print(f"[INFO] Usando driver: {'psycopg3' if ver == 3 else 'psycopg2'}")

    # Carrega os novos alvos (cada sistema independente)
    targets = load_new_targets()
    if not targets:
        print("[INFO] Nenhum novo arquivo tratado encontrado (src/.target_*.txt e gestor.sql/supervisor.sql na raiz).")
        return

    # Processa cada sistema separadamente
    for t in targets:
        process_for_system(pg, cfg, t["system"], t["target_name"], t["content"], t["base_dir"])

    print("[OK] apply_db_updates finalizado com sucesso.")

if __name__ == "__main__":
    main()
