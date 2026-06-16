import numpy as np
import sys
import os

# Adjust path to import from app
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.portfolio_sim import simulate

def test_kelly_simulation():
    # 20 steps of price data
    close = np.array([100.0 + i * 2.0 for i in range(20)])
    open_ = np.array([99.0 + i * 2.0 for i in range(20)])
    high = np.array([101.0 + i * 2.0 for i in range(20)])
    low = np.array([98.0 + i * 2.0 for i in range(20)])
    
    # Generate signals
    entries = np.zeros(20, dtype=bool)
    exits = np.zeros(20, dtype=bool)
    
    # Enter at index 1, exit at index 5
    # Enter at index 7, exit at index 11
    # Enter at index 13, exit at index 17
    entries[1] = True
    exits[5] = True
    entries[7] = True
    exits[11] = True
    entries[13] = True
    exits[17] = True
    
    # Run with KELLY
    init_cash = 10000.0
    risk_r = 100.0 # UI sends 100 as default
    
    # Simulate first day
    prev_stats = {
        "win_count": 4,
        "loss_count": 2,
        "total_win_pnl": 400.0,
        "total_loss_pnl": 100.0,
        "win_rate": 4 / 6,
        "avg_win": 100.0,
        "avg_loss": 50.0
    }
    
    print("--- TEST Scenario 1: Full Kelly (risk_r = 100), prev_stats present ---")
    results = simulate(
        close=close,
        open_=open_,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=init_cash,
        risk_r=100.0,
        risk_type="KELLY",
        prev_stats=prev_stats,
    )
    print(f"First trade size (Expected ~48.54): {results['trades'][0]['size']}")

    print("\n--- TEST Scenario 2: Half Kelly (risk_r = 50), prev_stats present ---")
    results_half = simulate(
        close=close,
        open_=open_,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=init_cash,
        risk_r=50.0,
        risk_type="KELLY",
        prev_stats=prev_stats,
    )
    print(f"First trade size (Expected ~24.27): {results_half['trades'][0]['size']}")

    print("\n--- TEST Scenario 3: Bootstrap (no stats / under 5 trades), Full Kelly (risk_r = 100) ---")
    results_boot = simulate(
        close=close,
        open_=open_,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=init_cash,
        risk_r=100.0,
        risk_type="KELLY",
        prev_stats=None,
    )
    # 2% default risk_amount = 10000.0 * 0.02 = 200.0. Size = 200.0 / 103.0 = 1.9417
    print(f"Bootstrap first trade size (Expected ~1.94): {results_boot['trades'][0]['size']}")

    print("\n--- TEST Scenario 4: Bootstrap, Half Kelly (risk_r = 50) ---")
    results_boot_half = simulate(
        close=close,
        open_=open_,
        high=high,
        low=low,
        entries=entries,
        exits=exits,
        direction="longonly",
        init_cash=init_cash,
        risk_r=50.0,
        risk_type="KELLY",
        prev_stats=None,
    )
    # 1% default risk_amount = 10000.0 * 0.01 = 100.0. Size = 100.0 / 103.0 = 0.97087
    print(f"Bootstrap first trade size (Expected ~0.97): {results_boot_half['trades'][0]['size']}")

if __name__ == "__main__":
    test_kelly_simulation()
