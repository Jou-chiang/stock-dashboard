# test_price_adapter.py
import os
import sys

# Add stock radar path
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from price_adapter import load_price_adapter

print("=" * 75)
print("UNIT TEST: L2 PLUGGABLE PRICE ADAPTER & MA/SIGNAL FAIL-SAFE GUARDS")
print("=" * 75)

# Test 1: Adjusted 2330
p_adj = load_price_adapter("2330", base_dir=BASE_DIR, prefer_adjusted=True)
print(f"\n[Test 1] 2330 (Adjusted Mode):")
print(f"  * price_basis: {p_adj.price_basis}")
print(f"  * is_valid_for_ma: {p_adj.is_valid_for_ma}")
print(f"  * rows count: {len(p_adj.rows)}")
print(f"  * latest close: {p_adj.latest_close}")
print(f"  * MA20: {p_adj.get_ma(20)}")
print(f"  * MA60: {p_adj.get_ma(60)}")
print(f"  * Max close since 2026-06-01: {p_adj.get_max_close_since('2026-06-01')}")

assert p_adj.price_basis == "adjusted"
assert p_adj.is_valid_for_ma == True
assert p_adj.get_ma(20) is not None
assert p_adj.get_ma(60) is not None
print("  => PASS: Adjusted series successfully computes MA & MaxClose")

# Test 2: Unadjusted Fallback for 2330 (simulating fallback)
p_raw = load_price_adapter("2330", base_dir=BASE_DIR, prefer_adjusted=False)
print(f"\n[Test 2] 2330 (Unadjusted Fallback Mode):")
print(f"  * price_basis: {p_raw.price_basis}")
print(f"  * is_valid_for_ma: {p_raw.is_valid_for_ma}")
print(f"  * rows count: {len(p_raw.rows)}")
print(f"  * latest close: {p_raw.latest_close}")
print(f"  * MA20: {p_raw.get_ma(20)}")
print(f"  * MA60: {p_raw.get_ma(60)}")
print(f"  * Max close since 2026-06-01: {p_raw.get_max_close_since('2026-06-01')}")

assert p_raw.price_basis == "unadjusted"
assert p_raw.is_valid_for_ma == False
assert p_raw.get_ma(20) is None
assert p_raw.get_ma(60) is None
assert p_raw.get_max_close_since('2026-06-01') is None
print("  => PASS: Unadjusted series strictly forces MA & MaxClose to None (Zero Hallucination Guard)")

# Test 3: Unknown or non-portfolio stock (e.g. 9999)
p_unknown = load_price_adapter("9999", base_dir=BASE_DIR, prefer_adjusted=True)
print(f"\n[Test 3] Unknown Stock 9999:")
print(f"  * price_basis: {p_unknown.price_basis}")
print(f"  * is_valid_for_ma: {p_unknown.is_valid_for_ma}")
print(f"  * MA20: {p_unknown.get_ma(20)}")

assert p_unknown.price_basis == "unadjusted"
assert p_unknown.is_valid_for_ma == False
assert p_unknown.get_ma(20) is None
print("  => PASS: Missing stock safely handled without crashing")

print("\n" + "=" * 75)
print("ALL PRICE ADAPTER TESTS PASSED PERFECTLY!")
print("=" * 75)
