"""Architecture guards (docs/b2d-gateway/06 EPIC F).

1. IP isolation: no module under api_public *imports* the engine internals
   (engine.py / indicators.py / portfolio_sim.py). The only permitted bridge is
   facade.py, and even it bridges through the high-level orchestrator/service
   layer, never the JIT engine modules. We inspect real import statements via AST
   (not comments/docstrings).
2. The OpenAPI document generates and exposes the contract paths.
"""
from __future__ import annotations

import ast
import pathlib

from app.api_public.app import app

# Substrings that, if they appear in an imported module path, mean we reached into
# the protected engine internals.
FORBIDDEN_IMPORTS = ("backtester.engine", "services.indicators", "services.portfolio_sim")

API_DIR = pathlib.Path(__file__).resolve().parents[1]


def _imported_modules(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    mods: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                mods.append(node.module)
    return mods


def test_no_engine_imports_anywhere():
    offenders = []
    for path in API_DIR.rglob("*.py"):
        if "tests" in path.parts:
            continue
        for mod in _imported_modules(path):
            for needle in FORBIDDEN_IMPORTS:
                if needle in mod:
                    offenders.append(f"{path.name}: imports {mod}")
    assert not offenders, f"IP isolation violated: {offenders}"


def test_facade_bridges_only_via_orchestrator():
    """facade.py may bridge to the engine, but only through the orchestrator/service
    layer — never the JIT engine modules directly."""
    facade = API_DIR / "facade.py"
    mods = _imported_modules(facade)
    for mod in mods:
        for needle in FORBIDDEN_IMPORTS:
            assert needle not in mod, f"facade.py imports engine internals: {mod}"
    # And it really does go through the orchestrator.
    assert any("backtest_orchestrator" in m for m in mods)


def test_openapi_generates_with_contract_paths():
    schema = app.openapi()
    paths = schema["paths"]
    for p in (
        "/v1/backtests",
        "/v1/backtests/{job_id}",
        "/v1/backtests/{job_id}/intraday",
        "/v1/strategies/validate",
        "/v1/universe/preview",
        "/v1/catalog/indicators",
        "/v1/health",
    ):
        assert p in paths, f"missing path in OpenAPI: {p}"
    assert schema["info"]["title"] == "Edgecute Backtest API"
