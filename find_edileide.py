from backend.app.processor import clear_process_cache, process_workspace_reports
import pandas as pd
from pathlib import Path

clear_process_cache()
result = process_workspace_reports()

# Procura pela Edileide
edileide = [c for c in result.all_collaborators if 'edileide' in c.get('nome', '').lower()]

print('Búsqueda por Edileide:')
print('-' * 80)
for c in edileide:
    print(f'Nome: {c.get("nome")}')
    print(f'CPF (normalizado): {c.get("cpf")} (len={len(c.get("cpf", ""))})')
    print(f'CPF formatado: {c.get("cpf_formatado")}')
    print()

# Também vamos procurar nos arquivos originais
print('Búsqueda nos arquivos Excel:')
print('-' * 80)
relatorios = Path('Relatórios')
for arquivo in relatorios.glob('*.xlsx'):
    try:
        df = pd.read_excel(arquivo)
        if 'nome' in df.columns or 'Nome' in df.columns:
            col_nome = next((c for c in df.columns if c.lower() == 'nome'), None)
            col_cpf = next((c for c in df.columns if c.lower() == 'cpf'), None)
            
            if col_nome and col_cpf:
                matches = df[df[col_nome].astype(str).str.lower().str.contains('edileide', na=False)]
                if not matches.empty:
                    print(f'Arquivo: {arquivo.name}')
                    for idx, row in matches.iterrows():
                        nome = row.get(col_nome, '')
                        cpf = row.get(col_cpf, '')
                        print(f'  Nome: {nome}, CPF original: {cpf} (tipo: {type(cpf).__name__})')
                    print()
    except Exception as e:
        pass
