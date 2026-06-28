"""The ONLY bridge between the public API and the engine (docs/b2d-gateway/05 §2).

Rules:
  * Imports of the heavy core (orchestrator/services) are LAZY (inside methods) so
    importing this module stays cheap and the API layer is testable without numba.
  * PROHIBITED: importing engine.py, indicators.py, portfolio_sim.py directly.
  * Engine errors are translated to safe ApiError — never leak `str(exc)`/traces.
  * NOTE: backtester/backtest_validator.py validates RESULTS (VectorBT), not input;
    strategy validation is Pydantic (modules/backtest/models.py), not here.

The Facade is injectable (get_facade / set_facade) so tests swap a fake with no
engine dependency.
"""
from __future__ import annotations

from typing import Optional

from app.api_public.core.errors import ApiError


class Facade:
    """Thin pass-through to the existing engine services."""

    def preview_universe(
        self,
        dataset_id: str,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        preconditions: Optional[list] = None,
        apply_day: str = "gap_day",
    ) -> dict:
        """Resolve an EXISTING dataset to its qualifying ticker-days. (Filter-based
        universe creation is v2 — see router.)"""
        from app.services.data_service import fetch_qualifying_data

        try:
            df = fetch_qualifying_data(
                dataset_id, date_from, date_to, preconditions=preconditions, apply_day=apply_day
            )
        except Exception as exc:  # noqa: BLE001 — translate, never leak
            raise ApiError(
                "invalid_universe",
                "No se pudo resolver el universo para ese dataset.",
            ) from exc

        if df is None or getattr(df, "empty", True):
            return {"ticker_days": 0, "tickers": 0}
        try:
            ticker_days = int(df[["ticker", "date"]].drop_duplicates().shape[0])
            tickers = int(df["ticker"].nunique())
        except Exception:
            ticker_days = int(len(df))
            tickers = 0
        return {"ticker_days": ticker_days, "tickers": tickers}

    def run_backtest(self, request_kwargs: dict) -> dict:
        """Run a backtest via the existing orchestrator. Returns the raw result dict."""
        from fastapi import HTTPException
        from app.services.backtest_orchestrator import (
            BacktestRequest,
            run_backtest_orchestrator,
        )

        try:
            req = BacktestRequest(**request_kwargs)
        except Exception as exc:  # noqa: BLE001
            raise ApiError("validation_error", "Parámetros de ejecución inválidos.") from exc

        try:
            return run_backtest_orchestrator(req)
        except HTTPException as exc:
            # 4xx carries domain-safe messages; 5xx must stay generic (no str(e)).
            if 400 <= exc.status_code < 500:
                code = "invalid_strategy" if exc.status_code == 404 else "invalid_universe"
                raise ApiError(code, str(exc.detail), status=422)
            raise ApiError("job_failed", "El backtest no se pudo completar.")
        except Exception as exc:  # noqa: BLE001
            raise ApiError("job_failed", "El backtest no se pudo completar.") from exc

    # ── Portfolio ────────────────────────────────────────────────────────────
    # Combine the owner's SAVED backtests (the Baul) into a portfolio and analyse
    # its risk. Pure analytics over already-computed results — does NOT touch the
    # heavy engine (no lazy engine import here, only the analytics service + DB
    # loader). Monitoring (3-month re-run) is NOT exposed in the commercial API
    # (it would hit the engine) — see docs/portfolio/04 §A.
    def _portfolio_returns(self, owner_id: Optional[str], backtest_ids: list, init_cash: float):
        from app.services.portfolio_loader import load_returns

        returns, labels, bad = load_returns(backtest_ids, owner_id, init_cash)
        if bad:
            raise ApiError(
                "invalid_backtest",
                "Algunos backtests no se pueden combinar.",
                details={"ids": bad},
            )
        return returns, labels

    def portfolio_combine(self, owner_id: Optional[str], kwargs: dict) -> dict:
        from app.services import portfolio_analytics_service as svc

        init_cash = kwargs.get("init_cash", svc.DEFAULT_INIT_CASH)
        returns, _ = self._portfolio_returns(owner_id, kwargs["backtest_ids"], init_cash)
        try:
            return svc.combine_returns(returns, kwargs.get("weights"), init_cash)
        except Exception as exc:  # noqa: BLE001
            raise ApiError("portfolio_failed", "No se pudo combinar la cartera.") from exc

    def portfolio_montecarlo(self, owner_id: Optional[str], kwargs: dict) -> dict:
        from app.services import portfolio_analytics_service as svc

        init_cash = kwargs.get("init_cash", svc.DEFAULT_INIT_CASH)
        returns, _ = self._portfolio_returns(owner_id, kwargs["backtest_ids"], init_cash)
        try:
            return svc.portfolio_montecarlo(
                returns, kwargs.get("weights"), kwargs.get("simulations", 1000), init_cash
            )
        except Exception as exc:  # noqa: BLE001
            raise ApiError("portfolio_failed", "No se pudo simular la cartera.") from exc

    def portfolio_correlation(self, owner_id: Optional[str], kwargs: dict) -> dict:
        from app.services import portfolio_analytics_service as svc

        returns, labels = self._portfolio_returns(owner_id, kwargs["backtest_ids"], svc.DEFAULT_INIT_CASH)
        if len(returns) < 2:
            raise ApiError("insufficient_strategies", "Necesitas al menos 2 estrategias.")
        try:
            return svc.correlation_matrices(returns, labels)
        except Exception as exc:  # noqa: BLE001
            raise ApiError("portfolio_failed", "No se pudo calcular la correlación.") from exc

    def portfolio_allocation(self, owner_id: Optional[str], kwargs: dict) -> dict:
        from app.services import portfolio_analytics_service as svc

        init_cash = kwargs.get("init_cash", svc.DEFAULT_INIT_CASH)
        returns, _ = self._portfolio_returns(owner_id, kwargs["backtest_ids"], init_cash)
        if kwargs["method"] == "hrp" and len(returns) < 2:
            raise ApiError("insufficient_strategies", "HRP necesita al menos 2 estrategias.")
        try:
            return svc.capital_allocation(
                returns, kwargs["method"], kwargs.get("lookback_days", 15),
                kwargs.get("leaders_weights"), init_cash,
            )
        except ApiError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ApiError("portfolio_failed", "No se pudo calcular la asignación.") from exc


# ── Injectable singleton ─────────────────────────────────────────────────────
_facade: Optional[Facade] = None


def get_facade() -> Facade:
    global _facade
    if _facade is None:
        _facade = Facade()
    return _facade


def set_facade(facade: Optional[Facade]) -> None:
    global _facade
    _facade = facade
