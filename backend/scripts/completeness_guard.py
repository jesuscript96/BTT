"""Guardia de completitud de la ingesta diaria.

Compara los tickers que guardamos en `daily_metrics` para un día contra los que
Massive dice que cotizaron ese día (grouped-daily) y GRITA si falta mercado.

Existe porque entre 2026-03 y 2026-07 la ingesta corrió en modo candidatos (solo
gap >= 5%) y `daily_metrics` quedó con el 5-7% del mercado durante CUATRO MESES
sin que nada fallara: el cron terminaba en verde, los ficheros pesaban lo normal
y el horario era correcto. Lo único que lo delataba era contar los tickers.

Uso (después del catchup, en el mismo cron):
    python scripts/completeness_guard.py            # comprueba el día anterior (NY)
    python scripts/completeness_guard.py 2026-07-13 # comprueba un día concreto

Sale con código 1 si el día está incompleto, para que el fallo sea visible.
"""
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from scripts.catchup_gcs import get_grouped_daily, logger  # noqa: E402

from app.database import get_db_connection  # noqa: E402

# Listón: un mes full-market bien ingerido da ~96%. El 4% que falta son IPOs de
# primer día (sin cierre previo no hay gap → el pipeline las descarta a propósito).
# Por debajo de 92% NO es ruido de IPOs: es que la ingesta se dejó mercado fuera.
MIN_PCT = float(os.getenv("COMPLETENESS_MIN_PCT", "92"))
WEBHOOK = os.getenv("ALERT_DISCORD_WEBHOOK", "").strip()


def avisar(titulo: str, detalle: str, grave: bool) -> None:
    """Deja el aviso en el log y, si hay webhook, en Discord."""
    (logger.error if grave else logger.info)(f"{titulo} — {detalle}")
    if not WEBHOOK:
        if grave:
            logger.error("  (sin ALERT_DISCORD_WEBHOOK: este aviso NO ha salido de aquí)")
        return
    try:
        r = requests.post(
            WEBHOOK,
            json={"content": f"{'🔴' if grave else '🟢'} **{titulo}**\n{detalle}"},
            timeout=15,
        )
        r.raise_for_status()
    except Exception as e:  # el aviso no debe tumbar nada, pero sí verse
        logger.error(f"  no se pudo avisar por Discord: {e}")


def main() -> int:
    if len(sys.argv) > 1:
        dia = sys.argv[1]
    else:
        # El cron corre a las 06:00 UTC (02:00 NY), así que "ayer en NY" es el
        # último día de mercado que el catchup debería haber ingerido.
        ayer = datetime.now(ZoneInfo("America/New_York")) - timedelta(days=1)
        dia = ayer.strftime("%Y-%m-%d")

    esperados = {r["T"] for r in get_grouped_daily(dia)}
    if not esperados:
        logger.info(f"[GUARDIA] {dia}: Massive no da datos (festivo o fin de semana). Nada que comprobar.")
        return 0

    con = get_db_connection()
    guardados = con.execute(
        "SELECT COUNT(DISTINCT ticker) FROM daily_metrics WHERE CAST(timestamp AS DATE) = CAST(? AS DATE)",
        [dia],
    ).fetchone()[0]
    con.close()

    pct = 100.0 * guardados / len(esperados)
    resumen = (f"`{dia}`: {guardados:,} de {len(esperados):,} tickers "
               f"(**{pct:.1f}%**, mínimo {MIN_PCT:.0f}%)")

    if guardados == 0:
        avisar("BTT — la ingesta NO escribió NADA",
               f"{resumen}\nEl mercado abrió ese día. Revisar `/var/log/catchup_gcs.log`.", True)
        return 1

    if pct < MIN_PCT:
        avisar("BTT — día ingerido INCOMPLETO",
               f"{resumen}\nSíntoma del bug de 2026-03: la ingesta corriendo en modo "
               f"candidatos. Comprobar que el cron lleva `FULL_MARKET_ENABLED=true`.", True)
        return 1

    logger.info(f"[GUARDIA] OK — {dia}: {guardados:,}/{len(esperados):,} tickers ({pct:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
