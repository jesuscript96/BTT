import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent / "backend"))

from app.database import get_db_connection
from app.init_db import init_db

init_db()
con = get_db_connection()

asian_symbols = [
    'BABA', 'JD', 'PDD', 'BIDU', 'NIO', 'LI', 'XPEV', 'FUTU', 'TCOM', 'NTES', 'BILI', 'TAL', 'EDU', 'VIPS',
    'SONY', 'TM', 'MUFG', 'MFG', 'NMR', 'HMC', 'CAJ', 'ORIX', 'TAK', 'SMFG',
    'LPL', 'KB', 'SHG', 'SKM', 'TSM', 'UMC', 'ASX', 'HIMX',
    'INFY', 'WIT', 'HDB', 'IBN', 'MMYT', 'SE', 'GRAB'
]

print("\n--- Checking specific Asian tickers in massive.tickers ---")
placeholders = ", ".join([f"'{s}'" for s in asian_symbols])
rows = con.execute(f"""
    SELECT ticker, name, market, primary_exchange, type, active 
    FROM massive.tickers 
    WHERE ticker IN ({placeholders})
    ORDER BY ticker ASC
""").fetchdf()
print(rows)
