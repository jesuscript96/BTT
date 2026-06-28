"""The `portfolio` module: combine the owner's saved backtests into a portfolio
and analyse its risk (combine, Monte Carlo, correlation, capital allocation).

Pure analytics over already-computed results in the Baul — never touches the
heavy engine. Monitoring (3-month re-run) is intentionally NOT exposed here.
"""
