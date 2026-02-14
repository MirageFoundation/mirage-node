import time
import math
import requests
import base64
import json
import logging
from typing import Optional

# Configuration
NODE_URL = "http://127.0.0.1:5000"  # Backend URL
RPC_URL = "http://127.0.0.1:26657"  # CometBFT RPC
LCD_URL = "http://127.0.0.1:1317"   # Cosmos SDK REST

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
log = logging.getLogger(__name__)

# --- Helper Functions ---

def get_params():
    try:
        resp = requests.get(f"{NODE_URL}/api/get_parameters")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Failed to get params: {e}")
        return None

def get_difficulty_info():
    try:
        resp = requests.get(f"{NODE_URL}/api/get_network_stats")
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"Failed to get stats: {e}")
        return None

def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))

def calculate_expected_factor(steps: int, step_size: float) -> int:
    if steps == 0:
        return 1000
    base = 1000
    # factor = 1000 * (1 + step)^difficulty
    factor = base * math.pow(1 + step_size, steps)
    return _round_half_up(factor)

# --- Test Logic ---

def test_difficulty_ramp():
    log.info("Starting Difficulty Ramp Test...")

    # 1. Fetch initial parameters
    params = get_params()
    if not params:
        log.error("Could not fetch params. Is the node running?")
        return

    pow_step = params.get("pow_difficulty_step")
    min_diff = params.get("min_difficulty")
    
    log.info(f"Chain Params: pow_step={pow_step}, min_diff={min_diff}")

    if pow_step is None:
        log.error("pow_difficulty_step missing from params!")
        return

    # 2. Check current difficulty
    stats = get_difficulty_info()
    current_steps = stats.get("pow_difficulty", 0)
    
    log.info(f"Current Difficulty Steps: {current_steps}")

    # 3. Verify Factor Calculation
    # We can't easily verify the *chain's* internal factor directly via API 
    # (it exposes steps now), but we can verify that our local calculation matches
    # what the frontend/backend would expect.
    
    expected_factor = calculate_expected_factor(current_steps, pow_step)
    log.info(f"Expected Work Factor for step {current_steps}: {expected_factor}")
    
    # 4. Simulate Ramp Up (Conceptual)
    # To actually ramp up, we'd need to spam the network with valid PoW messages.
    # This is expensive and slow to test in a quick script without a GPU/optimized solver.
    # Instead, we will verify the *formula* logic for the next few steps.
    
    log.info("Verifying Ramp Formula for next 10 steps:")
    for i in range(1, 11):
        next_step = current_steps + i
        factor = calculate_expected_factor(next_step, pow_step)
        multiplier = factor / 1000.0
        log.info(f"  Step {next_step}: Factor {factor} ({multiplier:.2f}x)")
        
        # Sanity checks
        if i == 1:
            # Step 1 should be roughly 1 + step_size
            expected_mult = 1 + pow_step
            if abs(multiplier - expected_mult) > 0.01:
                log.error(f"  [FAIL] Step 1 multiplier {multiplier} != expected {expected_mult}")
            else:
                log.info("  [PASS] Step 1 multiplier matches")

    # 5. Verify API consistency
    # Ensure /get_parameters and /get_network_stats return consistent data
    params_diff = params.get("pow_difficulty")
    stats_diff = stats.get("pow_difficulty")
    
    if params_diff != stats_diff:
        log.error(f"[FAIL] Inconsistent difficulty! Params: {params_diff}, Stats: {stats_diff}")
    else:
        log.info(f"[PASS] API consistency check: {params_diff} == {stats_diff}")

    log.info("Test Complete.")

if __name__ == "__main__":
    test_difficulty_ramp()
