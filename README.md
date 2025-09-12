# Sync Scripts

Automatiza a criação, validação e versionamento de **scripts SQL** para os sistemas **Gestor** e **Supervisor**, sincronizando com um repositório **SVN** (TortoiseSVN/Subversion) e garantindo que os scripts sejam **testados** em bases PostgreSQL antes de entrarem no repositório.

> Pasta raiz do projeto (local): **Sync_Scrips/**

---

## Como funciona

1. Você cria **um arquivo na raiz** do projeto:
   - `gestor.sql` → gera um script numerado em `Scripts/Gestor/NNNN.0.GXX.sql`
   - `supervisor.sql` → gera um script numerado em `Scripts/Supervisor/NNNN.0.SXX.sql`  
   (onde `NNNN` é sequencial e `XX` são suas iniciais)

2. O pipeline roda em 4 etapas (scripts Python):
   1) **`sync_svn.py`**: sincroniza a pasta `Scripts/` com o servidor SVN.  
   2) **`preprocess_sql.py`**: trata o arquivo (`gestor.sql`/`supervisor.sql`):  
      - adiciona cabeçalho (autor, data, IP, sistema);  
      - insere `select * from sistema.fn_verifica_script('<ID>');` no início;  
      - **segmenta comandos** e insere o separador `---------- END OFF COMMAND ----------` sem duplicações;  
      - insere `select * from sistema.fn_atualiza_script('<ID>');` no fim;  
      - salva o arquivo **em ANSI (cp1252)**;  
      - mantém um **backup** do arquivo original para rollback.
   3) **`apply_db_updates.py`**: conecta nas **duas bases** de cada sistema (teste/dev), **aplica scripts pendentes** conforme a pasta do SVN, executa o **novo script completo** na **base de testes** e somente **`fn_atualiza_script('<ID>')`** na **base de desenvolvimento**.
   4) **`post_sync_sql.py`**: gera o arquivo numerado dentro de `Scripts/<Sistema>/`, faz **`svn add`** e **commit** (quando aplicável), apaga o `gestor.sql`/`supervisor.sql` da raiz e **limpa os backups**.  
      - Se **qualquer etapa falhar**, o backup do `gestor.sql`/`supervisor.sql` é **restaurado** automaticamente.

Você pode rodar tudo via:
- **macOS/Linux**: `./run_sync.sh`
- **Windows 11**: `run_sync_windows.cmd`
- **VS Code (tarefas)**: `Terminal → Run Task... → *Sincronizar novo script*`

---

## Pré-requisitos

### Comuns
- **Git** (para clonar o repositório).
- **Python 3.9+** (recomendado 3.11).
- **psycopg** (driver PostgreSQL):  
  ```bash
  python3 -m pip install --upgrade pip
  python3 -m pip install "psycopg[binary]"
  ```
  > Observação: usamos **psycopg v3** (com fallback para psycopg2 caso exista). A instalação acima evita dependências como `pg_config`.

- **Acesso ao repositório SVN** (HTTP/HTTPS).  
  Os **dados de acesso** (usuário/senha) devem ser solicitados ao **administrador do repositório**.

### macOS
- **Subversion (svn)**:
  ```bash
  brew install subversion
  ```
- Dar permissão de execução:
  ```bash
  chmod +x ./run_sync.sh
  ```
- (Opcional) VS Code.

### Windows 11
- **Subversion (svn)**: instale **TortoiseSVN** com a opção **“Command Line Tools”** habilitada  
  *ou* via Winget (linha de comando do VisualSVN):
  ```powershell
  winget install -e --id VisualSVN.CommandLine
  ```
- **VS Code** (opcional, recomendado).
- Se usar PowerShell e `.venv`, pode ser preciso:
  ```powershell
  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
  ```

---

## Instalação (passo a passo)

1) **Clonar o repositório**
```bash
git clone https://github.com/Market-Automacoes/sync_scripts.git
cd sync_scripts
# sua pasta local pode se chamar Sync_Scrips conforme seu ambiente
```

2) **Criar ambiente virtual (.venv)**
- macOS/Linux:
  ```bash
  python3 -m venv .venv
  source .venv/bin/activate
  ```
- Windows (CMD):
  ```bat
  py -3 -m venv .venv
  .venv\Scripts\activate
  ```
- Windows (PowerShell):
  ```powershell
  py -3 -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```

3) **Instalar dependências Python**
```bash
python -m pip install --upgrade pip
python -m pip install "psycopg[binary]"
```

4) **Subversion no PATH**
- macOS:
  ```bash
  brew install subversion
  svn --version
  ```
- Windows:
  - Garanta que `svn.exe` está no PATH (`svn --version` no terminal).

5) **Permissões (macOS)**
```bash
chmod +x ./run_sync.sh
```

6) **Criar `config.ini`** (veja modelos abaixo). **Todos os campos são obrigatórios.**  
   Os dados do SVN devem ser obtidos com o **administrador do repositório**.

---

## Execução

- **macOS/Linux**:
  ```bash
  ./run_sync.sh
  ```
- **Windows**:
  ```bat
  run_sync_windows.cmd
  ```

### Fluxo executado
1. `sync_svn.py` → `preprocess_sql.py` → `apply_db_updates.py` → `post_sync_sql.py`
2. Se der erro, **rollback**: o `gestor.sql`/`supervisor.sql` da raiz é restaurado do backup.
3. Em sucesso, o `gestor.sql`/`supervisor.sql` é removido da raiz e o numerado é **commitado no SVN**.

---

## VS Code (tarefas)

Crie o arquivo **`.vscode/tasks.json`** com o conteúdo abaixo (base fornecida por você):

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Sincronizar novo script",
      "type": "shell",
      "osx":   { "command": "./run_sync.sh" },
      "linux": { "command": "./run_sync.sh" },
      "windows": { "command": ".\\\\run_sync_windows.cmd" },
      "options": {
        "cwd": "${workspaceFolder}"
      },
      "presentation": {
        "reveal": "always",
        "panel": "dedicated",
        "clear": true
      },
      "problemMatcher": []
    }
  ]
}
```

Depois: **Terminal → Run Task… → “Sincronizar novo script”**.

---

## `config.ini` — exemplo (valores fictícios)

> **Todos os campos são obrigatórios.** Substitua pelos seus valores reais.  
> Os dados de acesso ao SVN devem ser solicitados ao **administrador do repositório**.

```ini
[auth]
svn_username = seu_usuario_svn
svn_password = sua_senha_svn

[user]
author_name = Seu Nome Completo
initials    = XX

# Par de bancos para GESTOR (teste e desenvolvimento)
[db_test_gestor]
host = 192.168.0.10
port = 5432
dbname = gestor_test
user = postgres
password = senha_teste

[db_dev_gestor]
host = 192.168.0.11
port = 5432
dbname = gestor_dev
user = postgres
password = senha_dev

# Par de bancos para SUPERVISOR (teste e desenvolvimento)
[db_test_supervisor]
host = 192.168.0.10
port = 5432
dbname = supervisor_test
user = postgres
password = senha_teste

[db_dev_supervisor]
host = 192.168.0.11
port = 5432
dbname = supervisor_dev
user = postgres
password = senha_dev
```

## `config.ini` — modelo em branco (copiar/colar)

```ini
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

---

## Estrutura do projeto (sugerida)

```
Sync_Scrips/
├─ run_sync.sh
├─ run_sync_windows.cmd
├─ sync_svn.py
├─ preprocess_sql.py
├─ apply_db_updates.py
├─ post_sync_sql.py
├─ restore_backups.py
├─ config.ini              # (IGNORADO pelo git)
├─ .gitignore
├─ .vscode/
│  └─ tasks.json
└─ Scripts/
   ├─ Gestor/
   └─ Supervisor/
```

> O `.gitignore` deve ignorar `Scripts/` e `config.ini` para evitar vazar dados e ruído de versionamento.

---

## Dicas & solução de problemas

- **Permissão negada (macOS)**: rode `chmod +x ./run_sync.sh`.
- **`svn: E170013 / E000065` (rede/proxy)**: o projeto cria um diretório de config *no-proxy* (`.svnconfig_noproxy`) e limpa variáveis de proxy. Verifique conectividade com `nc -vz <host> 80`.
- **UnicodeDecodeError ao ler .sql**: os arquivos tratados são salvos em **cp1252 (ANSI)**; o pipeline lê ANSI primeiro e tem *fallback* para UTF-8/Latin-1.
- **`pip`/Python não encontrados**: garanta que o Python 3 está instalado e no PATH. No mac, use `python3`; no Windows, `py -3`.
- **PowerShell bloqueando scripts (.venv)**: rode `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

---

## Notas importantes

- **Não faça commit do `config.ini`**. O arquivo contém credenciais e deve estar no `.gitignore`.
- **Todos os campos do `config.ini` são obrigatórios**.
- Os **dados do SVN** (usuário/senha/URL) devem ser obtidos com o **administrador do repositório**.
- O separador entre comandos SQL é:
  ```
  ---------- END OFF COMMAND ----------
  ```
  O `preprocess_sql.py` garante que **não existam duplicatas “vazias”**.
- Blocos `DO $$ ... $$` são tratados como **um único comando** (mesmo sem `;`).

---

Feito com ❤️ para acelerar a automação de scripts SQL.
