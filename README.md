# Sync Scripts

Automatiza a criação, validação e versionamento de **scripts SQL** para os sistemas **Gestor** e **Supervisor**, sincronizando com um repositório **SVN** (TortoiseSVN/Subversion) e garantindo que os scripts sejam **testados** em bases PostgreSQL antes de entrarem no repositório.

> Pasta raiz do projeto local: **Sync_Scripts/**

---

## Como funciona

1. Você cria **um arquivo na raiz** do projeto:
   - `gestor.sql` → gera um script numerado em `src/Scripts/Gestor/NNNN.0.GXX.sql`
   - `supervisor.sql` → gera um script numerado em `src/Scripts/Supervisor/NNNN.0.SXX.sql`  
     (onde `NNNN` é sequencial e `XX` são suas iniciais)

2. Ao rodar a automação:
   - **Sincroniza** a pasta `src/Scripts` com o repositório SVN.
   - **Prepara** o arquivo (`preprocess_sql.py`): adiciona cabeçalho, insere chamadas a  
     `sistema.fn_verifica_script('<ID>')` e `sistema.fn_atualiza_script('<ID>')` (sem `.sql`) e **segmenta** comandos com  
     `---------- END OFF COMMAND ----------`. Salva em **ANSI (cp1252)**.
   - **Atualiza as bases** (teste/dev) com `apply_db_updates.py`:
     - Coloca TEST e DEV no último script disponível da pasta do sistema (caso estejam desatualizadas).
     - Executa o **novo script completo** na TEST.
     - Executa **apenas** `select * from sistema.fn_atualiza_script('<ID>')` na DEV.
   - **Gera o arquivo numerado** dentro de `src/Scripts/<Sistema>/` e faz **commit no SVN** (`post_sync_sql.py`).
   - Se qualquer etapa falhar, restaura automaticamente o arquivo original (`restore_backups.py`).

---

## Estrutura do projeto

```
Sync_Scripts/
├─ config.ini                 # sua configuração local (NÃO versionar)
├─ .gitignore
├─ gestor.sql                 # (opcional) fonte bruta para Gestor
├─ supervisor.sql             # (opcional) fonte bruta para Supervisor
├─ .vscode/
│  └─ tasks.json              # task do VS Code (macOS/Windows)
└─ src/
   └─ Scripts/
      ├─ Gestor/              # working copy SVN dos scripts do Gestor
      └─ Supervisor/          # working copy SVN dos scripts do Supervisor
   ├─ run_sync.sh
   ├─ run_sync_windows.cmd
   ├─ sync_svn.py
   ├─ preprocess_sql.py
   ├─ apply_db_updates.py
   ├─ post_sync_sql.py
   ├─ restore_backups.py
   └─ .svnconfig_noproxy/     # gerada automaticamente para ignorar proxy no SVN
```

> **Importante:** `.venv/` (ambiente virtual Python) fica na **raiz** `Sync_Scripts/.venv`.

---

## Pré-requisitos

### Comuns
- Acesso ao repositório SVN (URL, usuário e senha).  
  > Contate o **administrador do repositório** para obter as credenciais.
- Acesso às bases PostgreSQL (TEST e DEV) para **Gestor** e **Supervisor**.
- **Python 3.10+** (recomendado).
- Dependências Python:
  ```bash
  python -m pip install --upgrade pip
  python -m pip install "psycopg[binary]"
  ```

### macOS
- **SVN client** via Homebrew:
  ```bash
  brew install subversion
  ```
- (Opcional) Python via Homebrew:
  ```bash
  brew install python
  ```

### Windows
1) **Desativar App Execution Aliases**  
   (evita o erro “Python não foi encontrado…” da Microsoft Store):  
   Configurações → **Aplicativos** → **Configurações avançadas de aplicativo** → **Aliases de execução do aplicativo**  
   → **Desative** `python.exe` e `python3.exe`.

2) **Instalar Python x64** em: <https://www.python.org/downloads/windows/>  
   No instalador, marque:
   - **Add python.exe to PATH**
   - **Install launcher for all users (recommended)**
   Depois de instalar, feche e reabra o PowerShell/Prompt.

3) **Habilitar execução de scripts no PowerShell** (necessário para ativar o venv):  
   > Execute **uma vez** no PowerShell (como seu usuário):
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
   ```

4) **Subversion (SVN) CLI**  
   - Instale o **TortoiseSVN** e habilite “Command line tools” durante a instalação  
     **ou** instale um cliente SVN dedicado (ex.: SlikSVN).

---

## Instalação e configuração

1. **Clone** o repositório:
   ```bash
   git clone https://github.com/Market-Automacoes/sync_scripts.git
   cd sync_scripts
   ```

2. **Crie o ambiente virtual** `.venv` na raiz:
   - **macOS / Linux:**
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     python -m pip install --upgrade pip
     python -m pip install "psycopg[binary]"
     ```
   - **Windows (PowerShell)** – após rodar o `Set-ExecutionPolicy` acima:
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     python -m pip install --upgrade pip
     python -m pip install "psycopg[binary]"
     ```
     > Alternativa sem mexer em ExecutionPolicy: abra **CMD** e use  
     > `.\.venv\Scriptsctivate.bat` para ativar o venv.

3. **Edite o `config.ini`** na raiz (exemplar abaixo).  
   > **Todos os campos são obrigatórios.** Não commite esse arquivo (está no `.gitignore`).

4. (Opcional) **VS Code**  
   O repositório já traz `/.vscode/tasks.json`. Você pode rodar a Task:
   - `Terminal → Run Task → "Sincronizar novo script"`
   - Ou criar um atalho (ex.: `Ctrl+Alt+Y`).

---

## `config.ini` — Exemplo (preencha com seus dados)

```ini
[svn]
url = http://192.168.60.160/svn/repo/Scripts

[auth]
svn_username = Nome
svn_password = Senha

[user]
initials    = NO
author_name = Nome completo

# === Conexões para GESTOR ===
[db_test_gestor]
host = 192.168.60.162
port = 5432
dbname = dbNome
user = postgres
password = senha

[db_dev_gestor]
host = 192.168.60.162
port = 5432
dbname = dbnome_dev
user = postgres
password = senha

# === Conexões para SUPERVISOR ===
[db_test_supervisor]
host = 192.168.60.162
port = 5432
dbname = dbnome
user = postgres
password = senha

[db_dev_supervisor]
host = 192.168.60.162
port = 5432
dbname = debnome_dev
user = postgres
password = senha
```

> **Atenção:** este arquivo contém credenciais. **Não** faça commit.

---

## Uso

### Via VS Code (recomendado)
- Abra a pasta do projeto no VS Code.
- Rode a task **“Sincronizar novo script”**:
  - macOS/Linux → executa `./src/run_sync.sh`
  - Windows → executa `.\src\run_sync_windows.cmd`
- O pipeline executa:
  1. `sync_svn.py` – sincroniza `src/Scripts` com o SVN.
  2. `preprocess_sql.py` – trata `gestor.sql`/`supervisor.sql` (cabeçalho, separadores, ANSI).
  3. `apply_db_updates.py` – aplica pendências + testa o novo script em TEST + marca em DEV.
  4. `post_sync_sql.py` – gera o arquivo numerado, adiciona ao SVN e faz commit.
  5. Em caso de erro, `restore_backups.py` **restaura** automaticamente seu arquivo original.

### Via terminal (manual)
- **macOS / Linux**
  ```bash
  source .venv/bin/activate
  ./src/run_sync.sh
  ```
- **Windows (PowerShell)**
  ```powershell
  .\.venv\Scripts\Activate.ps1
  .\srcun_sync_windows.cmd
  ```

---

## Observações importantes

- Os scripts tratados são salvos em **ANSI (cp1252)** para compatibilidade com os ambientes-alvo.
- As chamadas de versão **não incluem `.sql`** (ex.: `select * from sistema.fn_verifica_script('9342.0.GJO');`).
- A pasta `src/.svnconfig_noproxy/` é criada automaticamente para garantir que o cliente SVN **não use proxy** ao acessar a LAN (ex.: `192.168.*`).
- A pasta `src/Scripts/` é a **working copy** do SVN e **é ignorada** no Git (baixada do servidor SVN).

---

## Solução de problemas

- **“Python não foi encontrado…” (Windows)**  
  Desative os *App Execution Aliases*, instale o Python do site oficial com **“Add to PATH”** e reabra o terminal.

- **“Activate.ps1 não pode ser carregado…” (Windows / PowerShell)**  
  Rode **uma vez**:
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
  ```
  Ou ative o venv pelo **CMD** com `.\.venv\Scriptsctivate.bat`.

- **`psycopg` não instala**  
  Atualize o `pip` e instale a *wheel* binária:
  ```bash
  python -m pip install --upgrade pip
  python -m pip install "psycopg[binary]"
  ```

- **SVN não encontra o repositório / problema de proxy**  
  Verifique o `config.ini` (`[svn].url`) e credenciais. As chamadas SVN já usam um diretório de config que ignora proxy para `192.168.*`.

- **Rollback automático não aconteceu**  
  O rollback é acionado pelo wrapper (`run_sync.sh`/`.cmd`). Se rodar scripts isolados e ocorrer erro, execute manualmente:
  ```bash
  # macOS/Linux
  python src/restore_backups.py

  # Windows (PowerShell)
  .\.venv\Scripts\Activate.ps1
  python .\srcestore_backups.py
  ```
