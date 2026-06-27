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

    # ── Robustness module ────────────────────────────────────────────────────
    # Bridges to app.services.robustness_service (which only calls existing
    # services — never the JIT engine). Lazy imports keep this file cheap and
    # keep the IP-isolation guard green.

    def _robustness_trades(self, run_id: str) -> list:
        from app.services.robustness_service import _load_trades, RobustnessError

        try:
            trades, _ = _load_trades(run_id)
            return trades
        except RobustnessError as exc:
            raise self._robustness_api_error(exc) from exc

    @staticmethod
    def _robustness_api_error(exc) -> ApiError:
        status = 500 if exc.code == "PROCESSING_ERROR" else 422
        return ApiError(exc.code.lower(), exc.message, status=status)

    def robustness_montecarlo(self, run_id: str, **kwargs) -> dict:
        from app.services import robustness_service

        trades = self._robustness_trades(run_id)
        try:
            return robustness_service.run_montecarlo_bootstrap(trades, **kwargs)
        except robustness_service.RobustnessError as exc:
            raise self._robustness_api_error(exc) from exc
        except Exception as exc:  # noqa: BLE001 — never leak internals
            raise ApiError("processing_error", "El análisis no se pudo completar.") from exc

    def robustness_sensitivity(self, run_id: str, **kwargs) -> dict:
        from app.services import robustness_service

        trades = self._robustness_trades(run_id)
        try:
            return robustness_service.run_sensitivity(trades, **kwargs)
        except robustness_service.RobustnessError as exc:
            raise self._robustness_api_error(exc) from exc
        except Exception as exc:  # noqa: BLE001
            raise ApiError("processing_error", "El análisis no se pudo completar.") from exc

    def robustness_black_swan(self, run_id: str, **kwargs) -> dict:
        from app.services import robustness_service

        trades = self._robustness_trades(run_id)
        try:
            return robustness_service.run_black_swan(trades, **kwargs)
        except robustness_service.RobustnessError as exc:
            raise self._robustness_api_error(exc) from exc
        except Exception as exc:  # noqa: BLE001
            raise ApiError("processing_error", "El análisis no se pudo completar.") from exc

    def robustness_trade_count(self, run_id: str) -> int:
        """Number of trades behind a run (for metering)."""
        return len(self._robustness_trades(run_id))


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
