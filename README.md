# Sync Scripts

Automatiza a criação, validação e versionamento de **scripts SQL** para os sistemas **Gestor** e **Supervisor**, sincronizando com um repositório **SVN** e garantindo que os scripts sejam **testados** em bases PostgreSQL antes de serem enviados.

> Pasta raiz do projeto (local): **Sync_Scrips/**  
> Principais scripts de automação ficam em **Sync_Scrips/src/**

---

## Como funciona (resumo do fluxo)

1. Você cria **um arquivo na raiz** do projeto:
   - `gestor.sql` → será tratado e numerado como `NNNN.0.GXX.sql`
   - `supervisor.sql` → será tratado e numerado como `NNNN.0.SXX.sql`  
   (onde `NNNN` é sequencial e `XX` são suas iniciais em **[user].initials**)
2. Rode a *task* do VS Code **“Sincronizar novo script”** (ou execute manualmente `./src/run_sync.sh` no macOS/Linux ou `.\src\run_sync_windows.cmd` no Windows).
3. O pipeline executa, **nessa ordem**:
   - `sync_svn.py`: faz checkout/update de `src/Scripts` a partir do SVN.
   - `preprocess_sql.py`: trata o arquivo (`*.sql` da raiz), gera cabeçalho, delimita comandos por `---------- END OFF COMMAND ----------`, converte para **ANSI (cp1252)** e cria um **backup** do seu arquivo de origem.
   - `apply_db_updates.py`: lê `config.ini`, aplica pendências do diretório `Scripts/<Sistema>` nas bases **TEST** e **DEV** e executa o **novo** script completo em TEST. Em DEV, roda somente `select * from sistema.fn_atualiza_script('<ID>')`.
   - `post_sync_sql.py`: grava o arquivo numerado em `src/Scripts/<Sistema>/NNNN.0.[GS]XX.sql`, **adiciona/commita no SVN** (se houver WC) e **remove os arquivos de origem** da raiz. Em caso de falha, `restore_backups.py` restaura seu `gestor.sql/supervisor.sql` original.
4. Pronto! O arquivo numerado estará no repositório SVN e as bases alinhadas.

---

## Estrutura do projeto

```
Sync_Scrips/
├─ config.ini                 # Configurações locais (não versionar)
├─ .gitignore
├─ gestor.sql                 # (opcional) arquivo de entrada do Gestor
├─ supervisor.sql             # (opcional) arquivo de entrada do Supervisor
├─ .vscode/
│  └─ tasks.json              # Task “Sincronizar novo script”
└─ src/
   └─ Scripts/
      ├─ Gestor/              # Working copy do SVN (conteúdo versionado)
      └─ Supervisor/          # Working copy do SVN (conteúdo versionado)
   ├─ run_sync.sh
   ├─ run_sync_windows.cmd
   ├─ sync_svn.py
   ├─ preprocess_sql.py
   ├─ apply_db_updates.py
   ├─ post_sync_sql.py
   ├─ restore_backups.py
```

---

## Pré‑requisitos

### Comuns
- **Acesso ao repositório SVN** (“TortoiseSVN/Subversion”). Peça **usuário e senha** ao administrador do repositório.
- **PostgreSQL cliente** não é necessário localmente; o acesso é via rede.
- **Python 3.9+** (recomendado 3.10+).
- Pacote Python: `psycopg` (psycopg3, binário).

### macOS
- **Subversion (svn)**: `brew install subversion`
- Criar e usar ambiente virtual (opcional, recomendado):
  ```bash
  cd Sync_Scrips
  python3 -m venv .venv
  source .venv/bin/activate
  python3 -m pip install --upgrade pip
  python3 -m pip install "psycopg[binary]"
  ```
- Dar permissão de execução ao script:
  ```bash
  chmod +x ./src/run_sync.sh
  ```

### Windows (passo a passo do Python + PATH)
1. Baixe o **Windows installer (64-bit)** em: https://www.python.org/downloads/windows/
2. Execute o instalador e **marque** a opção **“Add python.exe to PATH”** na primeira tela.
3. Clique em **Customize installation** (opcional) e mantenha **pip** selecionado. Conclua a instalação.
4. Feche e **reabra** o Prompt/PowerShell.
5. Verifique:
   ```bat
   python --version
   pip --version
   ```
   Se **python** não for reconhecido, adicione manualmente ao **PATH** (variáveis de ambiente do Windows):
   - Usuário (ou Sistema) → *Path* → **Editar** → **Novo** e inclua, ajustando a sua versão:
     ```
     %LocalAppData%\Programs\Python\Python312\
     %LocalAppData%\Programs\Python\Python312\Scripts\
     ```
     (ou `C:\Users\<seu-usuario>\AppData\Local\Programs\Python\Python312\`).
6. Instale dependências no projeto (opcional: use venv):
   ```bat
   cd Sync_Scrips
   python -m venv .venv
   .venv\Scripts\activate
   python -m pip install --upgrade pip
   python -m pip install "psycopg[binary]"
   ```
7. **SVN no Windows** (necessário `svn.exe` no PATH):
   - Instale o **TortoiseSVN** e selecione **“Command line client tools”** durante a instalação, **ou**
   - Instale **Subversion** via pacote que inclua o cliente de linha de comando.
   - Verifique:
     ```bat
     svn --version
     ```

---

## Configuração (`config.ini`)

> **Todos os campos são obrigatórios.** Mantenha este arquivo **fora do Git** (já está no `.gitignore`).  
> Peça credenciais do SVN ao administrador do repositório.

**Exemplo (copie/cole e ajuste os valores):**
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

**Observações importantes**
- `[user].initials` deve ter **2 letras** (ex.: `JO`). Aparece no nome do arquivo `NNNN.0.[GS]XX.sql`.
- O sistema (`Gestor` ou `Supervisor`) é deduzido pelo **nome do arquivo de entrada** na raiz: `gestor.sql` ou `supervisor.sql`.
- Os scripts são salvos **em ANSI (cp1252)** após o tratamento.

---

## VS Code – Execução via Task

Arquivo **.vscode/tasks.json** (já incluso no projeto):
```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "Sincronizar novo script",
      "type": "shell",
      "osx":   { "command": "./src/run_sync.sh" },
      "linux": { "command": "./src/run_sync.sh" },
      "windows": { "command": ".\\\\src\\\\run_sync_windows.cmd" },
      "options": { "cwd": "${workspaceFolder}" },
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

**Atalho opcional** (arquivo **.vscode/keybindings.json** local do usuário):
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

---

## Execução manual (sem VS Code)

- **macOS / Linux**
  ```bash
  cd Sync_Scrips
  ./src/run_sync.sh
  ```

- **Windows**
  ```bat
  cd Sync_Scrips
  .\src\run_sync_windows.cmd
  ```

---

## Dicas e solução de problemas

- **Falhou em algum passo?** O pipeline chama `restore_backups.py` e restaura o `gestor.sql/supervisor.sql` original se o commit não ocorreu.
- **Separadores duplicados** não são gerados; o pré-processamento evita `END OFF COMMAND` seguidos sem conteúdo.
- **SVN com proxy**: o fluxo usa uma configuração “no-proxy” dentro de `src/.svnconfig_noproxy` para evitar interferência de proxy corporativo em redes locais.
- **psycopg**: usamos `psycopg[binary]` (psycopg3) para evitar dependências de `pg_config`/compilação local.
- **Ambiente virtual (`.venv`)**: recomendado manter na raiz do projeto para isolar dependências.
- **Compatibilidade**: scripts testados em macOS (zsh/bash) e Windows 11 (cmd.exe).

---

## Licença
Este repositório contém automações internas; verifique a política da sua organização antes de redistribuir.
