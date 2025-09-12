#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKUP_DIR   = ROOT / ".preprocess_backup"
PENDING_FILE = BACKUP_DIR / "pending.txt"

def main():
    if not PENDING_FILE.exists():
        print("[restore] nada a restaurar.")
        return
    lines = PENDING_FILE.read_text(encoding="utf-8").splitlines()
    restored = 0
    for line in lines:
        if "|" not in line: 
            continue
        orig_str, bkp_str = line.split("|", 1)
        orig = Path(orig_str)
        bkp  = Path(bkp_str)
        try:
            if bkp.exists():
                orig.parent.mkdir(parents=True, exist_ok=True)
                if orig.exists():
                    orig.unlink()
                os.replace(str(bkp), str(orig))  # overwrite atômico
                print(f"[restore] restaurado {orig.name} a partir de {bkp.name}")
                restored += 1
        except Exception as e:
            print(f"[restore][warn] falha restaurando {orig}: {e}", file=sys.stderr)
    # limpa estado
    try:
        if PENDING_FILE.exists():
            PENDING_FILE.unlink()
        if BACKUP_DIR.exists() and not any(BACKUP_DIR.iterdir()):
            BACKUP_DIR.rmdir()
    except Exception:
        pass
    print(f"[restore] {restored} arquivo(s) restaurado(s).")

if __name__ == "__main__":
    main()
