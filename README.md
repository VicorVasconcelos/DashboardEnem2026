# Dashboard ENEM 2026

> Projeto de dashboard para visualização de indicadores do ENEM 2026.

## Visão geral

Este repositório contém um dashboard em Python com backend em `backend/app` e recursos estáticos em `assets/`.

## Estrutura do projeto

- `dashboard_enem.py` — script principal (frontend/entry).
- `iniciar_dashboard_enem.bat` — atalho para iniciar no Windows.
- `requirements.txt` — dependências do projeto principal.
- `backend/` — código do backend (API/processor).
- `assets/` — CSS, scripts e templates usados pelo dashboard.

## Pré-requisitos

- Python 3.10+ (recomendado)
- Git (para enviar ao GitHub)

## Instalação (local)

1. Criar e ativar um ambiente virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Instalar dependências:

```powershell
pip install -r requirements.txt
pip install -r backend/requirements.txt
```

## Execução

- No Windows você pode usar o atalho:

```powershell
.\iniciar_dashboard_enem.bat
```

- Ou executar manualmente (exemplo):

```powershell
python dashboard_enem.py
# ou
python backend/app/main.py
```

## Como subir este README para o GitHub

Se você quiser que eu faça o push automaticamente a partir desta máquina, autorize-me a executar `git` aqui. Senão, execute os comandos abaixo no diretório do projeto:

```bash
git init
git add README.md
git commit -m "Add README"
git remote add origin https://github.com/VicorVasconcelos/DashboardEnem2026.git
git branch -M main
git push -u origin main
```

Observação: o `git push` exigirá credenciais (token ou SSH) configuradas localmente.

## Contribuição

Abra uma issue ou envie um pull request com melhorias e correções.

## Licença

MIT

---

Victor Vasconcelos - 61984385187
