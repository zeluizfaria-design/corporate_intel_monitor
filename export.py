"""Script utilitário para exportar os dados de um ticker para CSV via CLI."""
import sys
import csv
from pathlib import Path
from storage.database import Database

def export(ticker: str, days: int = 30):
    db = Database()
    articles = db.query_by_ticker(ticker, days=days)
    if not articles:
        print(f"Nenhum dado encontrado para {ticker.upper()} nos últimos {days} dias.")
        return
        
    filename = Path(f"export_{ticker.upper()}.csv")
    
    # Extrair as chaves do primeiro dicionário como cabeçalho
    fieldnames = list(articles[0].keys())
    
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # O módulo csv exige que os valores sejam serializáveis para string.
        # Caso exista algum dicionário ou lista, o DictWriter faz cast pra string,
        # o que costuma ser suficiente, mas podemos garantir se necessário.
        for row in articles:
            for k, v in row.items():
                if isinstance(v, (dict, list)):
                    row[k] = str(v)
            writer.writerow(row)
            
    print(f"Exportado com sucesso {len(articles)} registros para {filename.absolute()}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python export.py TICKER [dias_retroativos]")
        print("Exemplo: python export.py NVDA 30")
        sys.exit(1)
        
    ticker_arg = sys.argv[1]
    days_back = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    
    export(ticker_arg, days=days_back)
