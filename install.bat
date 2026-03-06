@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo  Corporate Intelligence Monitor - Instalador
echo ============================================================
echo.

REM --- Verifica Python ---
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Python nao encontrado. Instale Python 3.11+ em https://python.org
    pause
    exit /b 1
)
echo [OK] Python encontrado.

REM --- Detecta pasta do projeto (onde este .bat esta) ---
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
echo [OK] Projeto em: %PROJECT_DIR%

REM --- Instala dependencias ---
echo.
echo [INFO] Instalando dependencias Python...
python -m pip install --upgrade pip
python -m pip install httpx selectolax feedparser pdfplumber duckdb pydantic-settings datasketch
python -m pip install torch --index-url https://download.pytorch.org/whl/cpu
python -m pip install transformers mcp anthropic
python -m pip install apscheduler fastapi uvicorn websockets

if %errorlevel% neq 0 (
    echo [ERRO] Falha na instalacao das dependencias.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas.

REM --- Copia .env.example para .env se nao existir ---
if not exist "%PROJECT_DIR%\.env" (
    copy "%PROJECT_DIR%\.env.example" "%PROJECT_DIR%\.env" >nul
    echo [OK] Arquivo .env criado a partir do .env.example
    echo [ATENCAO] Edite o arquivo .env com suas credenciais.
) else (
    echo [OK] Arquivo .env ja existe.
)

REM --- Registra servidor MCP globalmente ---
echo.
echo [INFO] Registrando servidor MCP no Claude Code...

for /f "tokens=*" %%i in ('python -c "import sys; print(sys.executable)"') do set PYTHON_EXE=%%i

REM Cria .mcp.json na home do usuario
set "MCP_FILE=%USERPROFILE%\.mcp.json"
set "MCP_SERVER_PATH=%PROJECT_DIR%\mcp_server.py"
set "MCP_SERVER_PATH_ESC=%MCP_SERVER_PATH:\=\\%"
set "PYTHON_EXE_ESC=%PYTHON_EXE:\=\\%"

(
echo {
echo   "mcpServers": {
echo     "corporate-intel-monitor": {
echo       "command": "%PYTHON_EXE_ESC%",
echo       "args": ["%MCP_SERVER_PATH_ESC%"],
echo       "env": {
echo         "PYTHONPATH": "%MCP_SERVER_PATH_ESC:mcp_server.py=%"
echo       }
echo     }
echo   }
echo }
) > "%MCP_FILE%"

echo [OK] Servidor MCP registrado em: %MCP_FILE%

REM --- Teste rapido ---
echo.
echo [INFO] Testando importacoes...
python -c "from storage.database import Database; from processors.event_classifier import classify_event; print('[OK] Modulos carregados com sucesso')" 2>&1

echo.
echo ============================================================
echo  Instalacao concluida!
echo ============================================================
echo.
echo Proximos passos:
echo   1. Edite o arquivo .env com suas credenciais (opcional)
echo   2. Reinicie o VS Code para carregar o servidor MCP
echo   3. Teste: python main.py AAPL
echo.
pause
