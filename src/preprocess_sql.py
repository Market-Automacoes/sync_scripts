#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, re, sys, socket, subprocess, shutil
from pathlib import Path
from datetime import datetime
from configparser import ConfigParser
from typing import Optional

# ================== Caminhos (projeto reorganizado) ==================
THIS_DIR      = Path(__file__).resolve().parent     # src/
PROJECT_ROOT  = THIS_DIR.parent                     # raiz do repo
SCRIPTS_DIR   = THIS_DIR / "Scripts"                # src/Scripts
GESTOR_DIR    = SCRIPTS_DIR / "Gestor"
SUPERV_DIR    = SCRIPTS_DIR / "Supervisor"
CONFIG_PATH   = PROJECT_ROOT / "config.ini"         # config.ini na raiz

END_MARK        = "---------- END OFF COMMAND ----------"
TARGET_ENCODING = "cp1252"  # "ANSI" no Windows

# --- área de backup (mantém compatibilidade com post_sync_sql.py) ---
BACKUP_DIR   = THIS_DIR / ".preprocess_backup"      # src/.preprocess_backup
PENDING_FILE = BACKUP_DIR / "pending.txt"

# =========================== Backups ================================

def make_backup(src: Path) -> Path:
    """
    Copia os bytes originais do arquivo (na raiz) para src/.preprocess_backup
    e registra o par (orig|backup) em pending.txt para possível restauração.
    """
    BACKUP_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    bkp = BACKUP_DIR / f"{src.name}.bak-{stamp}"
    shutil.copy2(src, bkp)  # preserva bytes/encoding original
    with PENDING_FILE.open("a", encoding="utf-8") as f:
        f.write(f"{src.resolve()}|{bkp.resolve()}\n")
    print(f"[backup] {src.name} -> {bkp.name}")
    return bkp

# ====================== Config / utilidades =========================

def load_config():
    cfg = ConfigParser()
    if CONFIG_PATH.exists():
        cfg.read(CONFIG_PATH, encoding="utf-8")
    author   = cfg.get("user", "author_name", fallback="").strip()
    initials = cfg.get("user", "initials", fallback="").strip().upper()
    if not author:
        author = cfg.get("auth", "svn_username", fallback=os.getenv("USER","")).strip() or "Desconhecido"
    if not re.fullmatch(r"[A-Za-z]{2}", initials):
        print("ERRO: [user].initials deve ter 2 letras (ex.: JO). Ajuste em config.ini.", file=sys.stderr)
        sys.exit(2)
    return author, initials

def get_local_ip():
    # 1) Tenta via socket (funciona na maioria dos casos e é cross-platform)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
            return ip
    except Exception:
        pass

    # 2) Fallback por SO
    if os.name == "nt":
        # Windows: parseia "ipconfig" e pega o primeiro "IPv4..."
        try:
            out = subprocess.run(
                ["ipconfig"],
                text=True,
                capture_output=True,
                encoding="cp1252",   # evita lixo de encoding no PT-BR
                errors="ignore"
            )
            m = re.search(r'IPv4[^:\n]*:\s*([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)', out.stdout)
            if m:
                return m.group(1)
        except Exception:
            pass

    elif sys.platform == "darwin":
        # macOS: tenta en0/en1 como antes
        for iface in ("en0", "en1"):
            try:
                out = subprocess.run(["ipconfig", "getifaddr", iface], text=True, capture_output=True)
                ip = (out.stdout or "").strip()
                if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip):
                    return ip
            except Exception:
                pass

    else:
        # Linux/Outros: tenta hostname -I (primeiro IPv4)
        try:
            out = subprocess.run(["hostname", "-I"], text=True, capture_output=True)
            tokens = (out.stdout or "").strip().split()
            for tk in tokens:
                if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', tk):
                    return tk
        except Exception:
            pass

    # 3) Último recurso
    return "0.0.0.0"

def detect_system_and_letter(src: Path):
    name = src.name.lower()
    if name == "gestor.sql":
        return "Gestor", "G", GESTOR_DIR
    if name == "supervisor.sql":
        return "Supervisor", "S", SUPERV_DIR
    print(f"ERRO: arquivo não suportado: {src.name} (use gestor.sql ou supervisor.sql)", file=sys.stderr)
    sys.exit(2)

def next_seq_for(folder: Path, letter: str) -> int:
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

def already_processed(txt: str) -> bool:
    return "--#AUTOR" in txt and "fn_verifica_script(" in txt

def extract_existing_script_id(txt: str) -> Optional[str]:
    """
    Procura por: select * from sistema.fn_verifica_script('XXXX.Y.ZZ');
    Retorna XXXX.Y.ZZ (sem .sql), se achar.
    """
    m = re.search(r"fn_verifica_script\(\s*'([^']+)'\s*\)", txt, flags=re.IGNORECASE)
    if not m:
        return None
    script_id = m.group(1).strip()
    script_id = re.sub(r"\.sql$", "", script_id, flags=re.IGNORECASE)  # remove .sql se vier por engano
    return script_id or None

# =============== SPLITTER (robusto, sem separadores vazios) ===============

def split_sql(text: str):
    """
    Divide texto SQL em comandos:
      - respeita strings, comments, dollar-quoted ($$ ... $$ / $tag$ ... $tag$)
      - considera bloco DO $$...$$ como um comando mesmo sem ';' ao final
      - não retorna statements vazios
    """
    DO_OPEN_RE = re.compile(r'(?is)\bdo\s+(\$[a-zA-Z0-9_]*\$|\$\$)')
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    n = len(text)
    i = 0

    stmts, buf = [], []
    in_line_comment = in_block_comment = in_single = in_double = False
    dq_tag = None           # $tag$ atual (se dentro de dollar-quote)
    do_closing_tag = None   # se estamos num DO $tag$..., guarda $tag$ p/ fechar

    def flush():
        nonlocal buf
        stmt = "".join(buf).strip()
        if stmt:
            stmts.append(stmt)
        buf = []

    def starts_dollar_tag(pos):
        if text[pos] != '$': return None
        j = pos + 1
        while j < n and (text[j].isalnum() or text[j] == '_'):
            j += 1
        if j < n and text[j] == '$':
            return text[pos:j+1]  # $tag$
        if text[pos:pos+2] == "$$":
            return "$$"
        return None

    while i < n:
        c  = text[i]
        c2 = text[i+1] if i+1 < n else ""

        # Comentário de linha
        if in_line_comment:
            buf.append(c)
            if c == '\n':
                in_line_comment = False
            i += 1
            continue

        # Comentário em bloco
        if in_block_comment:
            buf.append(c)
            if c == '*' and c2 == '/':
                buf.append(c2); i += 2; in_block_comment = False
            else:
                i += 1
            continue

        # Dentro de dollar-quote
        if dq_tag:
            buf.append(c)
            if c == '$' and text[i:i+len(dq_tag)] == dq_tag:
                buf.extend(list(dq_tag[1:]))  # já adicionou 1 '$'
                i += len(dq_tag) - 1
                if do_closing_tag == dq_tag:  # fecha DO $$...$$ mesmo sem ';'
                    do_closing_tag = None
                    flush()
                dq_tag = None
            i += 1
            continue

        # Fora de strings/quotes/comments: detectar início de comentários
        if not in_single and not in_double:
            if c == '-' and c2 == '--':
                buf.append(c); buf.append(c2); i += 2; in_line_comment = True; continue
            if c == '/' and c2 == '*':
                buf.append(c); buf.append(c2); i += 2; in_block_comment = True; continue

        # Início de dollar-quote?
        if not in_single and not in_double and c == '$':
            tag = starts_dollar_tag(i)
            if tag:
                # heurística DO ...
                back = "".join(buf[-50:]).lower()
                if re.search(r'(?:^|\W)do\s*$', back):
                    do_closing_tag = tag
                dq_tag = tag
                buf.extend(list(tag)); i += len(tag); continue

        # Strings
        if not in_double and c == "'":
            in_single = not in_single
            buf.append(c); i += 1
            while in_single and i < n:
                ch = text[i]
                buf.append(ch); i += 1
                if ch == "'":
                    if i < n and text[i] == "'":  # escape ''
                        buf.append(text[i]); i += 1
                    else:
                        in_single = False
            continue

        if not in_single and c == '"':
            in_double = not in_double
            buf.append(c); i += 1
            continue

        # Fim de statement por ';'
        if c == ';' and not (in_single or in_double or in_line_comment or in_block_comment or dq_tag):
            buf.append(c)
            flush()
            i += 1
            continue

        buf.append(c)
        i += 1

    # resto
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)

    # Remove statements vazios
    return [s for s in (st.strip() for st in stmts) if s]

# =============== GERADOR (sem duplicar separadores) ===============

def build_output(script_id: str, final_name_with_ext: str, sistema: str, author: str, stmts: list[str]):
    """
    script_id: ex '9342.0.GJO' (sem .sql)
    final_name_with_ext: ex '9342.0.GJO.sql' (apenas para mensagens/logs)
    """
    now = datetime.now().strftime("%d/%m/%y %H:%M:%S")
    ip  = get_local_ip()

    parts = []
    wrote_since_sep = False  # controla se há conteúdo real antes de inserir um END_MARK

    def add(line=""):
        nonlocal wrote_since_sep
        parts.append(line)
        if line.strip() and line.strip() != END_MARK:
            wrote_since_sep = True

    def sep():
        nonlocal wrote_since_sep
        if wrote_since_sep:
            if not parts or parts[-1].strip() != END_MARK:
                add(END_MARK)
            parts.append("")  # linha vazia por legibilidade
            wrote_since_sep = False

    # Cabeçalho
    add("/*")
    add(f"--#AUTOR...: {author}")
    add(f"--#DATA....: {now} - IP: {ip}")
    add(f"--#SISTEMA.: {sistema}")
    add("*/")
    add("")
    # Verificação inicial (sem .sql)
    add(f"select * from sistema.fn_verifica_script('{script_id}');")
    add("")
    sep()

    # Comandos
    for s in stmts:
        s_clean = s.strip()
        if not s_clean:
            continue
        add(s_clean)
        sep()

    # Atualização final (sem .sql)
    add(f"select * from sistema.fn_atualiza_script('{script_id}');")
    add("")
    sep()

    out = "\n".join(parts).strip() + "\n"
    # Colapsa separadores duplicados, por via das dúvidas
    out = re.sub(rf"(?:{re.escape(END_MARK)}\s*){{2,}}", END_MARK + "\n\n", out)
    return out

# ====================== PIPELINE PRINCIPAL ======================

def process_one(src: Path, author: str, initials: str):
    """
    src: caminho do arquivo na RAIZ (PROJECT_ROOT / 'gestor.sql' ou 'supervisor.sql')
    Gera conteúdo tratado em ANSI no próprio arquivo da raiz
    e grava o sidecar .target_<sistema>.txt (em src/), contendo o ID sem .sql.
    """
    sistema, letter, dest_folder = detect_system_and_letter(src)
    dest_folder.mkdir(parents=True, exist_ok=True)

    raw = src.read_text(encoding="utf-8", errors="replace")

    if already_processed(raw):
        # Já tratado: extrai o ID existente e escreve o sidecar (sem .sql)
        script_id = extract_existing_script_id(raw)
        if not script_id:
            print(f"ERRO: {src.name} parece tratado, mas não encontrei fn_verifica_script('<ID>').", file=sys.stderr)
            sys.exit(2)
        # grava sidecar com ID (sem .sql) em src/
        (THIS_DIR / f".target_{sistema.lower()}.txt").write_text(script_id, encoding="utf-8")
        print(f"ℹ️ {src.name} já está tratado; ID detectado: {script_id}.")
        return f"{script_id}.sql"

    # Ainda não tratado: gera novo nome e conteúdo
    seq = next_seq_for(dest_folder, letter)
    final_name = f"{seq:04d}.0.{letter}{initials}.sql"  # ex: 9342.0.GJO.sql
    script_id  = final_name[:-4]                        # sem .sql

    # backup antes de sobrescrever (em src/.preprocess_backup)
    make_backup(src)

    stmts = split_sql(raw)
    out   = build_output(script_id, final_name, sistema, author, stmts)

    # Salvar como "ANSI" (Windows-1252) — no arquivo da RAIZ
    src.write_text(out, encoding=TARGET_ENCODING, errors="replace")
    print(f"✅ Tratado {src.name} -> alvo {final_name} ({sistema}) [salvo em {TARGET_ENCODING}]")

    # Sidecar (em src/) deve conter o ID sem .sql
    (THIS_DIR / f".target_{sistema.lower()}.txt").write_text(script_id, encoding="utf-8")
    return final_name

def main():
    author, initials = load_config()
    found = False
    for fname in ("gestor.sql", "supervisor.sql"):
        p = PROJECT_ROOT / fname       # procura na RAIZ
        if p.exists():
            process_one(p, author, initials); found = True
    if not found:
        print("ℹ️ Nada a tratar (gestor.sql/supervisor.sql não encontrados na raiz).")

if __name__ == "__main__":
    main()
