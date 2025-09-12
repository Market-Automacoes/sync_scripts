# Sync_Scripts

Automação para **gerar, validar e versionar** scripts SQL dos sistemas **Gestor** e **Supervisor** usando **SVN** (Subversion/TortoiseSVN) e **PostgreSQL**, com integração ao **VS Code** e *rollback* automático em caso de falhas.

> **Fluxo resumido:** você cria `gestor.sql` ou `supervisor.sql` na **raiz** → a pipeline trata e **numera** → aplica os scripts em **bancos de teste/dev** → cria o arquivo numerado em `src/Scripts/<Sistema>/` → faz **commit** no SVN. Se algo falhar, o arquivo original é **restaurado** do backup.

---

## 📂 Estrutura do projeto

```
Sync_Scrips/
├─ config.ini                  # Configurações (NÃO versionar com credenciais reais)
├─ .gitignore
├─ gestor.sql                  # (opcional) entrada para o sistema Gestor
├─ supervisor.sql              # (opcional) entrada para o sistema Supervisor
├─ .vscode/
│  └─ tasks.json               # Task do VS Code (macOS/Windows)
└─ src/
   ├─ Scripts/                 # Working copy do SVN
   │  ├─ Gestor/
   │  └─ Supervisor/
   ├─ .svnconfig_noproxy/      # Config SVN sem proxy (gerado automaticamente)
   ├─ .preprocess_backup/      # Backups automáticos dos *.sql de entrada
   ├─ run_sync.sh              # Pipeline (macOS/Linux)
   ├─ run_sync_windows.cmd     # Pipeline (Windows)
   ├─ sync_svn.py              # 1) Sincroniza WC do SVN
   ├─ preprocess_sql.py        # 2) Trata/numera/cabeçalho/separadores/ANSI
   ├─ apply_db_updates.py      # 3) TEST completo; DEV apenas marca via função
   ├─ post_sync_sql.py         # 4) Cria numerado + commit + limpeza/rollback
   └─ restore_backups.py       # Restauração manual de backups, se preciso
```

> **Importante:** crie **apenas** `gestor.sql` ou `supervisor.sql` na raiz. **Não edite** diretamente os numerados em `src/Scripts/...` — eles são gerados pela pipeline.

---

## 🔧 O que cada etapa faz

1. **`sync_svn.py`**  
   Atualiza/baixa a working copy do SVN em `src/Scripts/` a partir de `SVN_URL`.

2. **`preprocess_sql.py`**  
   - Faz **backup** do arquivo de entrada (`src/.preprocess_backup/…`).  
   - Descobre o próximo número **sequencial** (ex.: `9342.0.GJO.sql` ou `0690.0.SJO.sql`).  
   - Gera **cabeçalho** com Autor, Data+IP e Sistema.  
   - Adiciona no topo:  
     `select * from sistema.fn_verifica_script('<ID>');` (**sem** `.sql`)  
   - Separa cada comando com `---------- END OFF COMMAND ----------` **sem duplicar separadores vazios**.  
   - Adiciona no final:  
     `select * from sistema.fn_atualiza_script('<ID>');` (**sem** `.sql`)  
   - Salva o arquivo de entrada em **ANSI (cp1252)**.  
   - Cria `.target_<sistema>.txt` com o `<ID>` (ex.: `9342.0.GJO`).

3. **`apply_db_updates.py`**  
   - Lê pares de conexões **TEST/DEV** por sistema (**Gestor** e/ou **Supervisor**).  
   - **Aplica pendências** dos diretórios `src/Scripts/<Sistema>/` até a última versão disponível (usando os separadores para rodar por blocos).  
   - Executa o **novo script completo** em **TEST**.  
   - Em **DEV**, executa **apenas**: `select * from sistema.fn_atualiza_script('<ID>');` (sem `.sql`).  
   - Se qualquer execução falhar, interrompe e permite **rollback** do arquivo de entrada a partir do backup.

4. **`post_sync_sql.py`**  
   - Gera o arquivo **numerado final** em `src/Scripts/<Sistema>/` com o conteúdo tratado (ANSI).  
   - Faz `svn add` e `svn commit` (se `src/Scripts` for uma working copy).  
   - **Sucesso:** remove `gestor.sql`/`supervisor.sql` da raiz e **limpa** os backups pendentes.  
   - **Falha:** restaura automaticamente o arquivo original da raiz a partir do backup.

> A pasta `src/.svnconfig_noproxy/` é criada automaticamente e **força exceção de proxy** para endereços locais (ex.: `192.168.*`).

---

## ✅ Pré‑requisitos

### Comuns
- Acesso ao **SVN** (URL + credenciais).  
- Acesso às **bases PostgreSQL** (TEST/DEV para cada sistema).  
- **Python 3.9+**.

### macOS (Sequoia ou superior)
- **SVN (Subversion)**: `brew install subversion`  
- **Python** (se necessário): `brew install python`  
- **Pacotes Python**:
  ```bash
  python3 -m pip install --upgrade pip
  python3 -m pip install "psycopg[binary]"
  ```
- **Permissão de execução** (uma vez):
  ```bash
  chmod +x src/run_sync.sh
  ```

### Windows 11
- **Python 3.9+** (ativar “Add Python to PATH” no instalador).
- **SVN CLI** (TortoiseSVN com “command line tools” ou `choco install svn`).
- **Pacotes Python**:
  ```bat
  py -3 -m pip install --upgrade pip
  py -3 -m pip install "psycopg[binary]"
  ```

---

## 🧪 Ambiente virtual (`.venv` na raiz)

Crie o **.venv** na **raiz do projeto** (não dentro de `src/`). O script `src/run_sync.sh` tenta ativá‑lo automaticamente.

**macOS/Linux:**
```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install "psycopg[binary]"
```

**Windows (PowerShell):**
```ps1
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
py -3 -m pip install --upgrade pip
py -3 -m pip install "psycopg[binary]"
```

---

## ⚙️ Configuração (`config.ini`)

> **Todos os campos são obrigatórios.**  
> Os dados do repositório SVN (URL, usuário, senha) devem ser solicitados ao **administrador**.

### Modelo em branco (copiar/colar)

```ini
[svn]
url = 

[auth]
svn_username = 
svn_password = 

[user]
author_name = 
initials    = 

[db_test_gestor]
host = 
port = 5432
dbname = 
user = 
password = 

[db_dev_gestor]
host = 
port = 5432
dbname = 
user = 
password = 

[db_test_supervisor]
host = 
port = 5432
dbname = 
user = 
password = 

[db_dev_supervisor]
host = 
port = 5432
dbname = 
user = 
password = 
```

### Exemplo preenchido (valores fictícios)

```ini
[svn]
url = http://192.168.60.160/svn/repo/Scripts

[auth]
svn_username = seu_usuario
svn_password = sua_senha

[user]
author_name = Seu Nome Sobrenome
initials    = AB

[db_test_gestor]
host = 192.168.60.10
port = 5432
dbname = gestor_test
user = postgres
password = secret

[db_dev_gestor]
host = 192.168.60.11
port = 5432
dbname = gestor_dev
user = postgres
password = secret

[db_test_supervisor]
host = 192.168.60.12
port = 5432
dbname = supervisor_test
user = postgres
password = secret

[db_dev_supervisor]
host = 192.168.60.13
port = 5432
dbname = supervisor_dev
user = postgres
password = secret
```

---

## ▶️ Como usar

### VS Code (recomendado)
- Abra a pasta **Sync_Scrips** no VS Code.
- Use a task **“Sincronizar novo script”** (já incluída em `.vscode/tasks.json`):  
  - **macOS/Linux:** roda `./src/run_sync.sh`  
  - **Windows:** roda `.\src\run_sync_windows.cmd`  
- Saída aparece no terminal integrado. Em falhas, o backup do arquivo de entrada é restaurado automaticamente.

**Atalho opcional** (por usuário): adicione em `keybindings.json`:
```json
[
  {
    "key": "ctrl+alt+y",
    "command": "workbench.action.tasks.runTask",
    "args": "Sincronizar novo script",
    "when": "workspaceFolderCount > 0"
  }
]
```

### Terminal (manual)

**macOS/Linux:**
```bash
./src/run_sync.sh
```

**Windows (Prompt):**
```bat
.\src\run_sync_windows.cmd
```

---

## 🧠 Regras de nomeação e conteúdo

- Arquivos são numerados como `NNNN.0.GXX.sql` (Gestor) ou `NNNN.0.SXX.sql` (Supervisor).  
  - `NNNN` = sequencial de 4 dígitos no diretório correspondente.  
  - `G`/`S` = sistema.  
  - `XX` = suas iniciais (2 letras) vindas de `config.ini` → `[user].initials`.
- O **ID do script** (sem `.sql`) é usado nas funções:
  - `select * from sistema.fn_verifica_script('<ID>');`
  - `select * from sistema.fn_atualiza_script('<ID>');`
- O arquivo tratado é salvo em **ANSI (cp1252)** para compatibilidade com ferramentas legadas.
- O “splitter” entende **DO $$ ... $$**, strings, comentários, *dollar‑quotes*, e evita **separadores duplicados vazios**.

---

## 🔁 Rollback automático

- Antes de sobrescrever `gestor.sql`/`supervisor.sql`, é criado um **backup** em `src/.preprocess_backup/` e registrado em `pending.txt`.  
- Se a pipeline falhar, `src/restore_backups.py` restaura o arquivo original da raiz.  
- Após **commit** bem‑sucedido, os registros de backup são limpos.

Você também pode restaurar manualmente:
```bash
python3 src/restore_backups.py
```

---

## 🧭 Dicas

- **Compartilhamento do projeto**: você pode versionar `.vscode/tasks.json` (cross‑platform). O `keybindings.json` é tipicamente por usuário.  
- **Proxy**: a pasta `src/.svnconfig_noproxy/` é gerada automaticamente para ignorar proxy em sub-redes locais.  
- **Erros de build do driver**: use **`psycopg[binary]`** (evita depender de `pg_config`).  
- **SVN**: credenciais do repositório devem ser solicitadas ao **administrador**.

---

## 📜 Licença

Este projeto é disponibilizado “como está”, voltado para automações internas. Ajuste conforme sua realidade e políticas de segurança.
