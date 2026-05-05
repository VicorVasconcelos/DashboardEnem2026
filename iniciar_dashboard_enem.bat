@echo off
setlocal

cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"

if exist "%PYTHON_EXE%" (
    echo Iniciando Dashboard ENEM com a virtualenv do projeto...
    "%PYTHON_EXE%" -m streamlit run "%~dp0dashboard_enem.py" --server.address 0.0.0.0 --server.port 8501 --server.headless true
) else (
    echo Virtualenv nao encontrada. Tentando usar o Python do sistema...
    python -m streamlit run "%~dp0dashboard_enem.py" --server.address 0.0.0.0 --server.port 8501 --server.headless true
)

if errorlevel 1 (
    echo.
    echo Nao foi possivel iniciar o Streamlit.
    echo Verifique se as dependencias estao instaladas e tente novamente.
    pause
)

endlocal
