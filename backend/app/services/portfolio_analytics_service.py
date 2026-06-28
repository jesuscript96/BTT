"""
Portfolio analytics service — combine saved backtests into a portfolio and
analyse its risk.

NOT to be confused with `portfolio_sim.py`, which is the per-strategy numpy
*engine* simulator. This module operates a level up: it takes ALREADY-COMPUTED
backtests from the Baul (`backtest_results.results_json`) and treats each as a
daily-return stream, then combines / correlates / simulates them as a portfolio.

Design rules (see docs/portfolio/):
  * All analytical logic lives here; routers stay thin.
  * Pure functions take `returns_by_id` (a dict id -> {date -> daily_return}) so
    they are unit-testable WITHOUT a database. DB loaders are separate.
  * ZERO lookahead in the leaders allocation and account-scaling simulations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

import numpy as np

# Returns are stored as fractions: 0.012 == +1.2%.
DEFAULT_INIT_CASH = 10000.0
RUIN_FRACTION = 0.10  # equity below 10% of init_cash counts as ruin (matches montecarlo_service)
TRADING_DAYS = 252


# ─────────────────────────────────────────────────────────────────────────────
# 1. Extraction: results_json -> daily returns
# ─────────────────────────────────────────────────────────────────────────────
def _epoch_to_date(epoch_seconds: int) -> str:
    return datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc).strftime("%Y-%m-%d")


def daily_returns_from_results_json(
    results_json: dict, capital_base: float = DEFAULT_INIT_CASH
) -> Dict[str, float]:
    """Derive a {date -> daily_return} map from a stored backtest result.

    Primary source: `global_equity` (the per-calendar-day equity curve, always
    present and compact). Fallback: reconstruct from `trades` grouped by date.
    Returns {} when neither is usable (caller raises `invalid_backtest`).
    """
    points = results_json.get("global_equity") or []
    if isinstance(points, list) and len(points) >= 2:
        out: Dict[str, float] = {}
        prev = _safe_float(points[0].get("value"))
        for p in points[1:]:
            cur = _safe_float(p.get("value"))
            r = (cur / prev - 1.0) if prev else 0.0
            out[_epoch_to_date(p.get("time", 0))] = r
            prev = cur
        return out

    # Fallback: group trade PnL by calendar date (no compounding).
    trades = results_json.get("trades") or []
    if isinstance(trades, list) and trades:
        base = capital_base if capital_base > 0 else DEFAULT_INIT_CASH
        daily_pnl: Dict[str, float] = {}
        for t in trades:
            date = t.get("date")
            if not date:
                continue
            daily_pnl[date] = daily_pnl.get(date, 0.0) + _safe_float(t.get("pnl"))
        return {d: pnl / base for d, pnl in daily_pnl.items()}

    return {}


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 2. Alignment
# ─────────────────────────────────────────────────────────────────────────────
def align_returns(returns_by_id: Dict[str, Dict[str, float]]) -> tuple[List[str], List[str], np.ndarray]:
    """Align all strategies onto the calendar UNION of their dates.

    A day where a strategy has no data is imputed as 0.0 (PRD §1.2).
    Returns (ids, dates_sorted, matrix) where matrix has shape (n_days, n_ids).
    """
    ids = list(returns_by_id.keys())
    all_dates = sorted({d for series in returns_by_id.values() for d in series.keys()})
    if not ids or not all_dates:
        return ids, all_dates, np.zeros((0, len(ids)), dtype=np.float64)

    matrix = np.zeros((len(all_dates), len(ids)), dtype=np.float64)
    date_idx = {d: i for i, d in enumerate(all_dates)}
    for j, _id in enumerate(ids):
        for d, r in returns_by_id[_id].items():
            matrix[date_idx[d], j] = r
    return ids, all_dates, matrix


def normalize_weights(
    ids: List[str], weights: Optional[Dict[str, float]]
) -> np.ndarray:
    """Return a numpy weight vector aligned to `ids`. None -> equal weight."""
    if not ids:
        return np.zeros(0)
    if not weights:
        return np.full(len(ids), 1.0 / len(ids))
    vec = np.array([float(weights.get(_id, 0.0)) for _id in ids], dtype=np.float64)
    total = vec.sum()
    if total <= 0:
        return np.full(len(ids), 1.0 / len(ids))
    return vec / total  # tolerate small drift; renormalise


# ─────────────────────────────────────────────────────────────────────────────
# 3. Metrics
# ─────────────────────────────────────────────────────────────────────────────
def equity_from_returns(port_returns: np.ndarray, init_cash: float) -> np.ndarray:
    """Compound a daily-return vector into an equity curve (len = n_days + 1)."""
    equity = np.empty(len(port_returns) + 1, dtype=np.float64)
    equity[0] = init_cash
    if len(port_returns):
        equity[1:] = init_cash * np.cumprod(1.0 + port_returns)
    return equity


def drawdown_from_equity(equity: np.ndarray) -> np.ndarray:
    running_max = np.maximum.accumulate(equity)
    return np.where(running_max > 0, (equity / running_max - 1.0) * 100.0, 0.0)


def compute_metrics(port_returns: np.ndarray, equity: np.ndarray) -> Dict[str, float]:
    if len(port_returns) == 0:
        return {
            "total_return_pct": 0.0, "max_drawdown_pct": 0.0, "sharpe_ratio": 0.0,
            "volatility_pct": 0.0, "win_rate_pct": 0.0, "profit_factor": 0.0, "n_days": 0,
        }
    total_return = (equity[-1] / equity[0] - 1.0) * 100.0 if equity[0] else 0.0
    dd = drawdown_from_equity(equity)
    std = float(np.std(port_returns))
    mean = float(np.mean(port_returns))
    sharpe = (mean / std * np.sqrt(TRADING_DAYS)) if std > 0 else 0.0
    wins = port_returns[port_returns > 0]
    losses = port_returns[port_returns < 0]
    win_rate = len(wins) / len(port_returns) * 100.0
    sum_win = float(wins.sum())
    sum_loss = float(np.abs(losses.sum()))
    profit_factor = (sum_win / sum_loss) if sum_loss > 0 else 0.0
    return {
        "total_return_pct": round(total_return, 2),
        "max_drawdown_pct": round(float(np.min(dd)), 2),
        "sharpe_ratio": round(sharpe, 3),
        "volatility_pct": round(std * 100.0, 3),
        "win_rate_pct": round(win_rate, 2),
        "profit_factor": round(profit_factor, 3),
        "n_days": int(len(port_returns)),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 4. Combine (Phase 1)
# ─────────────────────────────────────────────────────────────────────────────
def portfolio_returns(matrix: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Weighted daily portfolio return: sum_i w_i * r_i,t."""
    if matrix.shape[0] == 0:
        return np.zeros(0)
    return matrix @ weights


def combine_returns(
    returns_by_id: Dict[str, Dict[str, float]],
    weights: Optional[Dict[str, float]] = None,
    init_cash: float = DEFAULT_INIT_CASH,
) -> dict:
    """Combine aligned daily returns into a portfolio equity/drawdown + metrics."""
    ids, dates, matrix = align_returns(returns_by_id)
    w = normalize_weights(ids, weights)
    port_ret = portfolio_returns(matrix, w)
    equity = equity_from_returns(port_ret, init_cash)
    dd = drawdown_from_equity(equity)

    # timestamps: one per equity point. First point = day before first date.
    timestamps = _timestamps_for_curve(dates)
    return {
        "timestamps": timestamps,
        "combined_equity": [round(float(v), 2) for v in equity],
        "combined_drawdown": [round(float(v), 4) for v in dd],
        "metrics": compute_metrics(port_ret, equity),
        "weights": {_id: round(float(wt), 6) for _id, wt in zip(ids, w)},
    }


def _timestamps_for_curve(dates: List[str]) -> List[int]:
    if not dates:
        return []
    def to_epoch(d: str) -> int:
        return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())
    first = to_epoch(dates[0]) - 86400  # point 0 is the day before
    return [first] + [to_epoch(d) for d in dates]


# ─────────────────────────────────────────────────────────────────────────────
# 5. Risk: Monte Carlo + VaR/CVaR (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────
def _var_cvar(port_ret: np.ndarray, alpha: float, init_cash: float) -> tuple[float, float, float, float]:
    """Return (var_pct, var_usd, cvar_pct, cvar_usd). Losses are negative."""
    if len(port_ret) == 0:
        return 0.0, 0.0, 0.0, 0.0
    q = (1.0 - alpha) * 100.0  # 95% -> 5th percentile
    var = float(np.percentile(port_ret, q))
    tail = port_ret[port_ret <= var]
    cvar = float(tail.mean()) if len(tail) else var
    return (round(var * 100.0, 2), round(var * init_cash, 2),
            round(cvar * 100.0, 2), round(cvar * init_cash, 2))


def portfolio_montecarlo(
    returns_by_id: Dict[str, Dict[str, float]],
    weights: Optional[Dict[str, float]] = None,
    simulations: int = 1000,
    init_cash: float = DEFAULT_INIT_CASH,
    seed: Optional[int] = None,
) -> dict:
    """Monte Carlo by shuffling the aggregated DAILY return stream."""
    ids, dates, matrix = align_returns(returns_by_id)
    w = normalize_weights(ids, weights)
    port_ret = portfolio_returns(matrix, w)
    n = len(port_ret)
    if n == 0:
        raise ValueError("no_overlap")

    rng = np.random.default_rng(seed)
    curves = np.empty((simulations, n + 1), dtype=np.float64)
    curves[:, 0] = init_cash
    for i in range(simulations):
        shuffled = rng.permutation(port_ret)
        curves[i, 1:] = init_cash * np.cumprod(1.0 + shuffled)

    pct_keys = [5, 25, 50, 75, 95]
    percentiles = {
        f"p{p}": [round(float(v), 2) for v in np.percentile(curves, p, axis=0)]
        for p in pct_keys
    }

    var95_pct, var95_usd, cvar95_pct, cvar95_usd = _var_cvar(port_ret, 0.95, init_cash)
    var99_pct, var99_usd, cvar99_pct, cvar99_usd = _var_cvar(port_ret, 0.99, init_cash)

    ruin_threshold = init_cash * RUIN_FRACTION
    ruin = int(np.sum(np.any(curves < ruin_threshold, axis=1)))

    return {
        "percentiles": percentiles,
        "var_95_pct": var95_pct, "var_95_usd": var95_usd,
        "var_99_pct": var99_pct, "var_99_usd": var99_usd,
        "cvar_95_pct": cvar95_pct, "cvar_95_usd": cvar95_usd,
        "cvar_99_pct": cvar99_pct, "cvar_99_usd": cvar99_usd,
        "ruin_probability": round(ruin / simulations * 100.0, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 6. Correlation matrices (Phase 2)
# ─────────────────────────────────────────────────────────────────────────────
def correlation_matrices(
    returns_by_id: Dict[str, Dict[str, float]],
    labels_by_id: Optional[Dict[str, str]] = None,
) -> dict:
    from scipy.stats import spearmanr

    ids, dates, matrix = align_returns(returns_by_id)
    n = len(ids)
    labels = [(labels_by_id or {}).get(_id, _id) for _id in ids]
    if n < 2 or matrix.shape[0] < 2:
        eye = [[1.0 if i == j else 0.0 for j in range(n)] for i in range(n)]
        return {"labels": labels, "pearson": eye, "spearman": eye}

    pearson = np.corrcoef(matrix, rowvar=False)
    pearson = np.nan_to_num(pearson, nan=0.0)
    np.fill_diagonal(pearson, 1.0)

    sp_raw, _ = spearmanr(matrix)
    if np.ndim(sp_raw) == 0:  # n==2 columns -> spearmanr returns a scalar
        val = float(np.nan_to_num(sp_raw))
        sp = np.array([[1.0, val], [val, 1.0]])
    else:
        sp = np.nan_to_num(np.asarray(sp_raw, dtype=np.float64), nan=0.0)
    np.fill_diagonal(sp, 1.0)

    return {
        "labels": labels,
        "pearson": [[round(float(x), 4) for x in row] for row in pearson],
        "spearman": [[round(float(x), 4) for x in row] for row in sp],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 7. Kelly (Phase 2/3)
# ─────────────────────────────────────────────────────────────────────────────
def kelly_fraction(port_ret: np.ndarray) -> float:
    """Portfolio-level Kelly: f* = p - (1-p)/b, with b = avg_win/|avg_loss|."""
    if len(port_ret) == 0:
        return 0.0
    wins = port_ret[port_ret > 0]
    losses = port_ret[port_ret < 0]
    if len(wins) == 0 or len(losses) == 0:
        return 0.0
    p = len(wins) / len(port_ret)
    avg_win = float(wins.mean())
    avg_loss = float(np.abs(losses.mean()))
    if avg_loss == 0:
        return 0.0
    b = avg_win / avg_loss
    f = p - (1.0 - p) / b
    return float(max(0.0, min(1.0, f)))


# ─────────────────────────────────────────────────────────────────────────────
# 8. Capital allocation: Leaders + HRP (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────
def _quasi_diag(link: np.ndarray, n: int) -> List[int]:
    link = link.astype(int)
    sort_ix = [link[-1, 0], link[-1, 1]]
    while max(sort_ix) >= n:
        new = []
        for i in sort_ix:
            if i >= n:
                new.extend([int(link[i - n, 0]), int(link[i - n, 1])])
            else:
                new.append(int(i))
        sort_ix = new
    return sort_ix


def _recursive_bisection(cov: np.ndarray, sort_ix: List[int]) -> np.ndarray:
    n = cov.shape[0]
    w = np.ones(n)
    clusters = [sort_ix]
    while clusters:
        clusters = [
            c[start:stop]
            for c in clusters
            for start, stop in ((0, len(c) // 2), (len(c) // 2, len(c)))
            if len(c) > 1
        ]
        for i in range(0, len(clusters), 2):
            c0, c1 = clusters[i], clusters[i + 1]
            v0 = _cluster_var(cov, c0)
            v1 = _cluster_var(cov, c1)
            alpha = 1.0 - v0 / (v0 + v1) if (v0 + v1) > 0 else 0.5
            for idx in c0:
                w[idx] *= alpha
            for idx in c1:
                w[idx] *= (1.0 - alpha)
    return w


def _cluster_var(cov: np.ndarray, items: List[int]) -> float:
    sub = cov[np.ix_(items, items)]
    ivp = 1.0 / np.diag(sub)
    ivp /= ivp.sum()
    return float(ivp @ sub @ ivp)


def hrp_weights(matrix: np.ndarray) -> np.ndarray:
    """Hierarchical Risk Parity weights (Lopez de Prado), scipy-only."""
    import scipy.cluster.hierarchy as sch
    from scipy.spatial.distance import squareform

    n = matrix.shape[1]
    if n == 0:
        return np.zeros(0)
    if n == 1:
        return np.ones(1)
    cov = np.cov(matrix, rowvar=False)
    corr = np.nan_to_num(np.corrcoef(matrix, rowvar=False), nan=0.0)
    np.fill_diagonal(corr, 1.0)
    dist = np.sqrt(np.clip((1.0 - corr) / 2.0, 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(dist, checks=False)
    link = sch.linkage(condensed, method="single")
    sort_ix = _quasi_diag(link, n)
    w = _recursive_bisection(cov, sort_ix)
    total = w.sum()
    return w / total if total > 0 else np.full(n, 1.0 / n)


def _leaders_weights_over_time(
    matrix: np.ndarray, lookback: int, leaders_weights: Optional[List[float]]
) -> np.ndarray:
    """Per-day weight matrix (n_days, n_ids) using ONLY past data (no lookahead).

    Each day t, rank strategies by trailing Sharpe over [t-lookback, t); assign
    `leaders_weights` (best->worst). Before enough history, use equal weight.
    """
    n_days, n = matrix.shape
    out = np.full((n_days, n), 1.0 / n)
    if leaders_weights:
        base = np.array(leaders_weights[:n], dtype=np.float64)
        if len(base) < n:
            base = np.concatenate([base, np.zeros(n - len(base))])
    else:
        base = np.arange(n, 0, -1, dtype=np.float64)  # N, N-1, ..., 1
    base = base / base.sum() if base.sum() > 0 else np.full(n, 1.0 / n)

    for t in range(n_days):
        if t < lookback:
            continue
        window = matrix[t - lookback:t]  # strictly past
        mean = window.mean(axis=0)
        std = window.std(axis=0)
        score = np.divide(mean, std, out=mean.copy(), where=std > 0)
        order = np.argsort(-score)  # best first
        w = np.zeros(n)
        for rank, idx in enumerate(order):
            w[idx] = base[rank]
        out[t] = w
    return out


def capital_allocation(
    returns_by_id: Dict[str, Dict[str, float]],
    method: str,
    lookback_days: int = 15,
    leaders_weights: Optional[List[float]] = None,
    init_cash: float = DEFAULT_INIT_CASH,
) -> dict:
    ids, dates, matrix = align_returns(returns_by_id)
    n = len(ids)
    if n == 0 or matrix.shape[0] == 0:
        raise ValueError("no_overlap")

    if method == "hrp":
        w_vec = hrp_weights(matrix)
        port_ret = portfolio_returns(matrix, w_vec)
        weights_map = {_id: round(float(wt), 6) for _id, wt in zip(ids, w_vec)}
    elif method == "leaders":
        w_time = _leaders_weights_over_time(matrix, lookback_days, leaders_weights)
        port_ret = np.einsum("tj,tj->t", matrix, w_time)
        avg_w = w_time.mean(axis=0)
        avg_w = avg_w / avg_w.sum() if avg_w.sum() > 0 else avg_w
        weights_map = {_id: round(float(wt), 6) for _id, wt in zip(ids, avg_w)}
    else:
        raise ValueError(f"unknown_method:{method}")

    equity = equity_from_returns(port_ret, init_cash)
    dd = drawdown_from_equity(equity)
    return {
        "weights": weights_map,
        "comparison_equity": [round(float(v), 2) for v in equity],
        "comparison_drawdown": [round(float(v), 4) for v in dd],
        "metrics": compute_metrics(port_ret, equity),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 9. Account scaling (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────
def account_scaling(
    returns_by_id: Dict[str, Dict[str, float]],
    weights: Optional[Dict[str, float]],
    init_cash: float = DEFAULT_INIT_CASH,
    mode: str = "kelly",
    kelly_frac: float = 0.5,
    fixed_pct: Optional[float] = None,
    dd_stop_pct: float = -20.0,
) -> dict:
    ids, dates, matrix = align_returns(returns_by_id)
    if matrix.shape[0] == 0:
        raise ValueError("no_overlap")
    w = normalize_weights(ids, weights)
    port_ret = portfolio_returns(matrix, w)

    if mode == "kelly":
        f = kelly_frac * kelly_fraction(port_ret)
        scaled = port_ret * f
        equity = equity_from_returns(scaled, init_cash)
    elif mode == "fixed_pct":
        f = fixed_pct if fixed_pct is not None else 1.0
        scaled = port_ret * f
        equity = equity_from_returns(scaled, init_cash)
    elif mode == "drawdown_stop":
        equity = _simulate_drawdown_stop(port_ret, init_cash, dd_stop_pct)
        scaled = port_ret  # for metrics we report realised path below
    else:
        raise ValueError(f"unknown_mode:{mode}")

    dd = drawdown_from_equity(equity)
    realised = np.diff(equity) / np.where(equity[:-1] != 0, equity[:-1], 1.0)
    return {
        "equity": [round(float(v), 2) for v in equity],
        "drawdown": [round(float(v), 4) for v in dd],
        "metrics": compute_metrics(realised, equity),
    }


def _simulate_drawdown_stop(port_ret: np.ndarray, init_cash: float, dd_stop_pct: float) -> np.ndarray:
    """Trade at full size until drawdown breaches dd_stop_pct, then sit out until
    a new high is reached. No lookahead — uses only the equity seen so far."""
    equity = np.empty(len(port_ret) + 1, dtype=np.float64)
    equity[0] = init_cash
    peak = init_cash
    stopped = False
    for t, r in enumerate(port_ret):
        cur = equity[t]
        dd = (cur / peak - 1.0) * 100.0 if peak > 0 else 0.0
        if not stopped and dd <= dd_stop_pct:
            stopped = True
        if stopped:
            equity[t + 1] = cur  # flat: out of the market
            if cur >= peak:
                stopped = False
        else:
            equity[t + 1] = cur * (1.0 + r)
        peak = max(peak, equity[t + 1])
    return equity
