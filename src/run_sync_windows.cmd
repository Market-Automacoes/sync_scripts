@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 1252 >nul

REM === Caminho deste .cmd (agora em Sync_Scrips\src) ===
set "SCRIPT_DIR=%~dp0"
pushd "%SCRIPT_DIR%" >nul

REM === Preferir Python do .venv local, se existir ===
set "PYEXE="
if exist "%SCRIPT_DIR%..\ .venv\Scripts\python.exe" (
  set "PYEXE=%SCRIPT_DIR%..\ .venv\Scripts\python.exe"
)

REM === Fallbacks: py -3 ou python do PATH ===
if not defined PYEXE where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
  echo [ERRO] Python nao encontrado no PATH.
  goto :fail
)

echo [1/4] Sincronizando Scripts (svn)...
%PYEXE% "%SCRIPT_DIR%sync_svn.py" %* || goto :fail

echo [2/4] Pre-processando gestor.sql/supervisor.sql...
%PYEXE% "%SCRIPT_DIR%preprocess_sql.py" || goto :fail

echo [3/4] Aplicando atualizacoes nas bases (teste/dev)...
%PYEXE% "%SCRIPT_DIR%apply_db_updates.py" || goto :fail

echo [4/4] Gerando arquivo numerado, commitando e limpando fontes...
%PYEXE% "%SCRIPT_DIR%post_sync_sql.py" || goto :fail

echo.
echo [OK] Fluxo concluido com sucesso.
popd >nul
exit /b 0

:fail
echo.
echo [FALHA] Processo interrompido por erro (veja acima).
REM >>> nome correto do script de restore (sem "s"):
%PYEXE% "%SCRIPT_DIR%restore_backups.py" 1>nul 2>nul
popd >nul
exit /b 1
