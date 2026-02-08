#!/bin/bash
# Automated Testing Suite for BTT
# Runs comprehensive tests on REAL MotherDuck data (locally executed)

echo "=== Automated Testing Suite ==="
echo "Running tests against REAL MotherDuck database..."
echo ""

# Navigate to backend directory
cd "$(dirname "$0")/.."

# Ensure .env is loaded (needed for MOTHERDUCK_TOKEN)
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file not found!"
    echo "   Tests need MOTHERDUCK_TOKEN to connect to database."
    exit 1
fi

echo "[1/2] Environment ready"
echo ""

# Run all tests
echo "[2/2] Running all tests..."
.venv_313/bin/pytest tests/ -v --tb=short --color=yes \
  --ignore=tests/test_strategy_search.py \
  --ignore=tests/verify_backtest_flow.py \
  || {
    echo "❌ Tests failed!"
    exit 1
  }
echo ""

echo "✅ All tests passed!"
echo ""
echo "📊 Generating HTML report..."
.venv_313/bin/pytest tests/ --html=tests/report.html --self-contained-html \
  --ignore=tests/test_strategy_search.py \
  --ignore=tests/verify_backtest_flow.py \
  >/dev/null 2>&1

echo "📊 Report available at: tests/report.html"
