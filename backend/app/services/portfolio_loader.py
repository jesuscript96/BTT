"""DB loader for the Portfolio module — kept separate from
`portfolio_analytics_service` so the maths stays unit-testable without a DB.

Used by BOTH the internal router (`routers/portfolio.py`) and the commercial API
facade (`api_public/facade.py`). Returns bad ids instead of raising, so each
caller maps the failure onto its own error type (HTTPException vs ApiError).
"""
from __future__ import annotations

import json
from typing import Dict, List, Optional, Tuple

from app.auth import scope_clause
from app.database import get_user_db_connection
from app.services import portfolio_analytics_service as svc


def load_returns(
    backtest_ids: List[str],
    user_id: Optional[str],
    capital_base: float = svc.DEFAULT_INIT_CASH,
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, str], List[str]]:
    """Return (returns_by_id, labels_by_id, bad_ids) for the caller's backtests,
    scoped by user_id (NULL-tolerant). Order of `backtest_ids` is preserved."""
    if not backtest_ids:
        return {}, {}, []

    placeholders = ",".join("?" for _ in backtest_ids)
    scope_sql, scope_params = scope_clause(user_id)
    sql = (
        f"SELECT id, results_json FROM backtest_results "
        f"WHERE id IN ({placeholders}){scope_sql}"
    )
    con = get_user_db_connection(read_only=True)
    try:
        rows = con.execute(sql, [*backtest_ids, *scope_params]).fetchall()
    finally:
        con.close()

    raw: Dict[str, dict] = {}
    for _id, results_json in rows:
        try:
            raw[_id] = results_json if isinstance(results_json, dict) else json.loads(results_json)
        except (TypeError, ValueError):
            continue

    returns_by_id: Dict[str, Dict[str, float]] = {}
    labels: Dict[str, str] = {}
    bad: List[str] = []
    for _id in backtest_ids:
        rj = raw.get(_id)
        series = svc.daily_returns_from_results_json(rj, capital_base) if rj else {}
        if not series:
            bad.append(_id)
            continue
        returns_by_id[_id] = series
        names = (rj.get("strategy_names") if isinstance(rj, dict) else None) or []
        labels[_id] = ", ".join(names) if names else _id[:8]

    return returns_by_id, labels, bad
