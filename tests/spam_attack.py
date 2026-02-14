#!/usr/bin/env python3
"""
Mirage Blockchain Spam Attack / Stress Test

Floods the blockchain with concurrent transactions from multiple workers.
Each worker has its own wallet and computes valid PoW to submit real transactions.

Uses conda environment: mirage-node

Run: conda activate mirage-node && python tests/spam_attack.py --backend http://127.0.0.1:80
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
import time
import random
import string
import math
import threading
from dataclasses import dataclass, field
from typing import Optional, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

# Make repo root importable
THIS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(THIS_DIR, ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from shared.client import (
    create_wallet_from_seed,
    get_status,
    sign_canonical,
)
from shared.canon import (
    canon_base_post as _canon_base_post_raw,
    canon_base_vote as _canon_base_vote_raw,
    canon_signed_with_pow,
)

# Defaults
DEFAULT_BACKEND = "http://127.0.0.1:80"
DEFAULT_WORKERS = 10
DEFAULT_DURATION = 60  # seconds


# Generate random seeds for spam workers (each worker gets unique wallet)
def _generate_seed() -> str:
    """Generate a random 12-word mnemonic-like seed."""
    words = [
        "abandon",
        "ability",
        "able",
        "about",
        "above",
        "absent",
        "absorb",
        "abstract",
        "absurd",
        "abuse",
        "access",
        "accident",
        "account",
        "accuse",
        "achieve",
        "acid",
        "acoustic",
        "acquire",
        "across",
        "act",
        "action",
        "actor",
        "actress",
        "actual",
        "adapt",
        "add",
        "addict",
        "address",
        "adjust",
        "admit",
        "adult",
        "advance",
        "advice",
        "aerobic",
        "affair",
        "afford",
        "afraid",
        "again",
        "age",
        "agent",
        "agree",
        "ahead",
        "aim",
        "air",
        "airport",
        "aisle",
        "alarm",
        "album",
        "alcohol",
        "alert",
        "alien",
        "all",
        "alley",
        "allow",
        "almost",
        "alone",
        "alpha",
        "already",
        "also",
        "alter",
        "always",
        "amateur",
        "amazing",
        "among",
    ]
    return " ".join(random.choices(words, k=12))


@dataclass
class SpamStats:
    """Thread-safe statistics collector."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    total_requests: int = 0
    successful: int = 0
    failed: int = 0
    retries: int = 0  # difficulty-change retries (not counted as failures)
    http_errors: int = 0
    pow_computed: int = 0
    start_time: float = 0.0
    status_codes: dict = field(default_factory=dict)
    error_types: dict = field(default_factory=dict)
    latencies: list = field(default_factory=list)
    # Per-difficulty PoW solve times: {difficulty: [solve_time_seconds, ...]}
    pow_times_by_difficulty: dict = field(default_factory=dict)

    def record(self, success: bool, status_code: int, latency: float, error: str = ""):
        with self.lock:
            self.total_requests += 1
            if success:
                self.successful += 1
            else:
                self.failed += 1
            if status_code >= 400:
                self.http_errors += 1
            self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1
            if error:
                key = error[:50]
                self.error_types[key] = self.error_types.get(key, 0) + 1
            self.latencies.append(latency)

    def record_retry(self):
        with self.lock:
            self.retries += 1

    def record_pow(self, difficulty: int, solve_time: float):
        with self.lock:
            self.pow_computed += 1
            if difficulty not in self.pow_times_by_difficulty:
                self.pow_times_by_difficulty[difficulty] = []
            self.pow_times_by_difficulty[difficulty].append(solve_time)

    def get_rps(self) -> float:
        elapsed = time.time() - self.start_time
        if elapsed <= 0:
            return 0.0
        return self.total_requests / elapsed

    def get_avg_latency(self) -> float:
        with self.lock:
            if not self.latencies:
                return 0.0
            return sum(self.latencies) / len(self.latencies)

    def get_p99_latency(self) -> float:
        with self.lock:
            if not self.latencies:
                return 0.0
            sorted_lat = sorted(self.latencies)
            idx = int(len(sorted_lat) * 0.99)
            return sorted_lat[min(idx, len(sorted_lat) - 1)]

    def print_pow_summary(self):
        """Print per-difficulty PoW solve time summary."""
        with self.lock:
            if not self.pow_times_by_difficulty:
                return
            print("\nPoW Solve Times by Difficulty:")
            print(f"  {'Diff':>4}  {'Count':>6}  {'Avg':>8}  {'Min':>8}  {'Max':>8}  {'Median':>8}")
            print(f"  {'----':>4}  {'-----':>6}  {'-------':>8}  {'-------':>8}  {'-------':>8}  {'-------':>8}")
            for diff in sorted(self.pow_times_by_difficulty.keys()):
                times = self.pow_times_by_difficulty[diff]
                count = len(times)
                avg = sum(times) / count
                mn = min(times)
                mx = max(times)
                sorted_t = sorted(times)
                median = sorted_t[count // 2]
                print(
                    f"  {diff:>4}  {count:>6}  {avg:>7.2f}s  {mn:>7.2f}s  {mx:>7.2f}s  {median:>7.2f}s"
                )


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("utf-8")


def _rand_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=n))


def _now_ms() -> int:
    return int(time.time() * 1000)


def _lb_bytes(lb_hex: str) -> bytes:
    try:
        return bytes.fromhex(lb_hex.strip())
    except Exception:
        return lb_hex.encode("utf-8")


def _uvarint(n: int) -> bytes:
    out = []
    while n >= 0x80:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


_BASE_DIFFICULTY_FACTOR = 1000
_MAX_SAFE_DIFFICULTY_FACTOR = (1 << 53) - 1
_POW_FACTOR: float | None = None


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _difficulty_factor(difficulty: int, pow_factor: float) -> int | None:
    if difficulty < 0:
        return None
    if not math.isfinite(pow_factor) or pow_factor <= 0 or pow_factor > 1:
        return None
    if difficulty == 0:
        return _BASE_DIFFICULTY_FACTOR
    try:
        factor = _BASE_DIFFICULTY_FACTOR * math.pow(1.0 + pow_factor, float(difficulty))
    except Exception:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if not math.isfinite(factor):
        return _MAX_SAFE_DIFFICULTY_FACTOR
    if factor > _MAX_SAFE_DIFFICULTY_FACTOR:
        return _MAX_SAFE_DIFFICULTY_FACTOR
    rounded = _round_half_up(factor)
    return max(_BASE_DIFFICULTY_FACTOR, rounded)


def _check_pow_target(digest: bytes, difficulty: int, pow_base_bits: int, pow_factor: float) -> bool:
    """Target-based PoW check. difficulty is steps (0=base, 1=+step, 2=+step^2)."""
    if pow_base_bits <= 0 or pow_base_bits > 256:
        return False
    factor = _difficulty_factor(difficulty, pow_factor)
    if factor is None:
        return False
    base_target = 1 << (256 - pow_base_bits)
    eff_target = base_target * _BASE_DIFFICULTY_FACTOR // factor
    return int.from_bytes(digest, "big") <= eff_target


def canon_base_post(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    topic: str,
    title: str,
    content: str,
    tag: str = "",
    pow_val: int = 0,
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _now_ms() if timestamp is None else int(timestamp)
    return _canon_base_post_raw(
        pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, target, topic, title, content, tag, pow_val
    )


def canon_base_vote(
    pubkey: bytes,
    last_block_hash_hex: str,
    difficulty: int,
    target: str,
    direction: int,
    timestamp: Optional[int] = None,
) -> bytes:
    ts = _now_ms() if timestamp is None else int(timestamp)
    return _canon_base_vote_raw(pubkey, _lb_bytes(last_block_hash_hex), int(difficulty), ts, target, int(direction))


def _compute_pow(
    base: bytes,
    difficulty: int,
    pow_base_bits: int,
    last_block_hash: str,
    max_seconds: float = 180.0,
    stop_check: callable = None,
) -> Tuple[int, float]:
    """Compute Argon2id PoW. Returns (proof, solve_time_seconds)."""
    try:
        from argon2.low_level import hash_secret_raw as _argon2_hash_raw, Type as _Argon2Type
    except Exception as e:
        raise RuntimeError("argon2-cffi is required for PoW") from e
    if difficulty < 0:
        raise ValueError("difficulty must be >= 0")
    if pow_base_bits <= 0 or pow_base_bits > 256:
        raise ValueError("pow_base_bits must be in [1, 256]")
    if _POW_FACTOR is None:
        raise ValueError("pow_factor missing")

    try:
        salt = bytes.fromhex(last_block_hash.strip())
    except Exception:
        salt = last_block_hash.encode("utf-8")

    start = time.perf_counter()
    proof = random.randint(0, 1000000)  # Random start to avoid collision
    check_interval = 100  # Check stop condition every N iterations
    while True:
        digest = _argon2_hash_raw(
            base + b":" + _uvarint(proof),
            salt,
            time_cost=1,
            memory_cost=4096,
            parallelism=1,
            hash_len=32,
            type=_Argon2Type.ID,
        )
        if _check_pow_target(digest, difficulty, pow_base_bits, _POW_FACTOR):
            return proof, time.perf_counter() - start
        if (time.perf_counter() - start) > max_seconds:
            raise TimeoutError(f"PoW not found in {max_seconds}s")
        # Check if we should stop early
        if stop_check and proof % check_interval == 0 and stop_check():
            raise InterruptedError("Worker stopped")
        proof += 1


def _fetch_params(backend: str, address: Optional[str] = None) -> Tuple[str, int, int]:
    """Fetch current block hash, difficulty, and pow_base_bits."""
    st = get_status(backend, address=address)
    last_block_hash = str(st.get("last_block_hash", "") or "")
    pow_difficulty = int(st.get("pow_difficulty", 0) or 0)
    pow_base_bits = int(st.get("pow_base_bits", 0) or 0)
    global _POW_FACTOR
    _POW_FACTOR = float(st["pow_factor"])
    return last_block_hash, pow_difficulty, pow_base_bits


def _post_json(url: str, payload: dict, timeout: float = 30.0) -> Tuple[int, dict]:
    r = requests.post(url, json=payload, timeout=timeout)
    ct = r.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            return r.status_code, r.json()
        except Exception:
            pass
    return r.status_code, {"status": r.status_code, "text": r.text[:300]}


class SpamWorker:
    """Single spam worker with its own wallet."""

    def __init__(self, worker_id: int, backend: str, stats: SpamStats, seed: Optional[str] = None):
        self.worker_id = worker_id
        self.backend = backend
        self.stats = stats
        self.seed = seed or _generate_seed()
        self.wallet = create_wallet_from_seed(self.seed)
        self.address = str(self.wallet.address())
        self.pub = self.wallet.public_key().public_key_bytes
        self.last_block_hash = ""
        self.difficulty = 0
        self.pow_base_bits = 0
        self.created_posts: List[str] = []
        self.running = True

    def refresh_params(self):
        """Refresh block hash and difficulty."""
        try:
            self.last_block_hash, self.difficulty, self.pow_base_bits = _fetch_params(self.backend, self.address)
        except Exception:
            pass

    def spam_post(self, _retry: int = 0) -> bool:
        """Create a spam post. Retries with refreshed params on difficulty mismatch."""
        try:
            if not self.last_block_hash:
                self.refresh_params()

            title = f"Spam {_rand_str(6)}"
            content = f"Spam content {_rand_str(20)} at {int(time.time())}"
            topic = f"spam{_rand_str(4)}"
            ts = _now_ms()
            used_difficulty = self.difficulty

            base = canon_base_post(
                self.pub, self.last_block_hash, used_difficulty, "", topic, title, content, "", 0, ts
            )

            proof, solve_time = _compute_pow(
                base,
                used_difficulty,
                self.pow_base_bits,
                self.last_block_hash,
                max_seconds=180.0,
                stop_check=lambda: not self.running,
            )
            self.stats.record_pow(used_difficulty, solve_time)

            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(self.wallet, signed)

            payload = {
                "pubkey": _b64(self.pub),
                "signature": _b64(sig),
                "last_block_hash": self.last_block_hash,
                "timestamp": ts,
                "pow_difficulty": int(used_difficulty),
                "pow": int(proof),
                "target": "",
                "topic": topic,
                "title": title,
                "content": content,
            }

            start = time.perf_counter()
            code, resp = _post_json(f"{self.backend}/api/core/post", payload)
            latency = time.perf_counter() - start

            success = code == 200 and "tx_hash" in resp
            error_msg = str(resp.get("error", resp.get("text", "")))[:80] if not success else ""

            # On insufficient pow or stale block hash, refresh params and retry once
            if not success and _retry < 2 and ("insufficient pow" in error_msg or "invalid last_block_hash" in error_msg):
                self.stats.record_retry()
                self.refresh_params()
                return self.spam_post(_retry=_retry + 1)

            self.stats.record(success, code, latency, error_msg[:50])

            if success:
                self.created_posts.append(resp.get("tx_hash", ""))

            # Refresh params periodically
            if random.random() < 0.1:
                self.refresh_params()

            return success

        except TimeoutError:
            self.stats.record(False, 0, 0, "PoW timeout")
            self.refresh_params()
            return False
        except InterruptedError:
            return False  # Worker stopped, don't record as failure
        except Exception as e:
            self.stats.record(False, 0, 0, str(e)[:50])
            return False

    def spam_vote(self, _retry: int = 0) -> bool:
        """Vote on a random post. Retries with refreshed params on difficulty mismatch."""
        try:
            if not self.last_block_hash:
                self.refresh_params()

            # Get a post to vote on
            target = None
            if self.created_posts:
                target = random.choice(self.created_posts)
            else:
                # Try to fetch a post from the server
                try:
                    r = requests.get(f"{self.backend}/api/get_posts", params={"limit": 20}, timeout=5.0)
                    if r.status_code == 200:
                        posts = r.json().get("posts", [])
                        if posts:
                            target = random.choice(posts).get("post_id", "")
                except Exception:
                    pass

            if not target:
                return False

            ts = _now_ms()
            direction = random.choice([-1, 1])
            used_difficulty = self.difficulty

            base = canon_base_vote(self.pub, self.last_block_hash, used_difficulty, target, direction, ts)

            proof, solve_time = _compute_pow(
                base,
                used_difficulty,
                self.pow_base_bits,
                self.last_block_hash,
                max_seconds=180.0,
                stop_check=lambda: not self.running,
            )
            self.stats.record_pow(used_difficulty, solve_time)

            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(self.wallet, signed)

            payload = {
                "pubkey": _b64(self.pub),
                "signature": _b64(sig),
                "last_block_hash": self.last_block_hash,
                "timestamp": ts,
                "pow_difficulty": int(used_difficulty),
                "pow": int(proof),
                "target": target,
                "direction": direction,
            }

            start = time.perf_counter()
            code, resp = _post_json(f"{self.backend}/api/core/vote", payload)
            latency = time.perf_counter() - start

            success = code == 200 and "tx_hash" in resp
            error_msg = str(resp.get("error", resp.get("text", "")))[:80] if not success else ""

            if not success and _retry < 2 and ("insufficient pow" in error_msg or "invalid last_block_hash" in error_msg):
                self.stats.record_retry()
                self.refresh_params()
                return self.spam_vote(_retry=_retry + 1)

            self.stats.record(success, code, latency, error_msg[:50])

            if random.random() < 0.1:
                self.refresh_params()

            return success

        except TimeoutError:
            self.stats.record(False, 0, 0, "PoW timeout")
            self.refresh_params()
            return False
        except InterruptedError:
            return False  # Worker stopped, don't record as failure
        except Exception as e:
            self.stats.record(False, 0, 0, str(e)[:50])
            return False

    def spam_comment(self, _retry: int = 0) -> bool:
        """Create a spam comment on an existing post. Retries on difficulty mismatch."""
        try:
            if not self.last_block_hash:
                self.refresh_params()

            # Get a post to comment on
            target = None
            if self.created_posts:
                target = random.choice(self.created_posts)
            else:
                # Try to fetch a post from the server
                try:
                    r = requests.get(f"{self.backend}/api/get_posts", params={"limit": 20}, timeout=5.0)
                    if r.status_code == 200:
                        posts = r.json().get("posts", [])
                        if posts:
                            target = random.choice(posts).get("post_id", "")
                except Exception:
                    pass

            if not target:
                # No target, create a post instead
                return self.spam_post()

            content = f"Spam comment {_rand_str(15)} at {int(time.time())}"
            ts = _now_ms()
            used_difficulty = self.difficulty

            # Comment: target is parent, topic/title are empty
            base = canon_base_post(
                self.pub, self.last_block_hash, used_difficulty, target, "", "", content, "", 0, ts
            )

            proof, solve_time = _compute_pow(
                base,
                used_difficulty,
                self.pow_base_bits,
                self.last_block_hash,
                max_seconds=180.0,
                stop_check=lambda: not self.running,
            )
            self.stats.record_pow(used_difficulty, solve_time)

            signed = canon_signed_with_pow(base, int(proof))
            sig = sign_canonical(self.wallet, signed)

            payload = {
                "pubkey": _b64(self.pub),
                "signature": _b64(sig),
                "last_block_hash": self.last_block_hash,
                "timestamp": ts,
                "pow_difficulty": int(used_difficulty),
                "pow": int(proof),
                "target": target,
                "topic": "",
                "title": "",
                "content": content,
            }

            start = time.perf_counter()
            code, resp = _post_json(f"{self.backend}/api/core/post", payload)
            latency = time.perf_counter() - start

            success = code == 200 and "tx_hash" in resp
            error_msg = str(resp.get("error", resp.get("text", "")))[:80] if not success else ""

            if not success and _retry < 2 and ("insufficient pow" in error_msg or "invalid last_block_hash" in error_msg):
                self.stats.record_retry()
                self.refresh_params()
                return self.spam_comment(_retry=_retry + 1)

            self.stats.record(success, code, latency, error_msg[:50])

            if random.random() < 0.1:
                self.refresh_params()

            return success

        except TimeoutError:
            self.stats.record(False, 0, 0, "PoW timeout")
            self.refresh_params()
            return False
        except InterruptedError:
            return False  # Worker stopped, don't record as failure
        except Exception as e:
            self.stats.record(False, 0, 0, str(e)[:50])
            return False

    def run(self, duration: float, mode: str = "mixed"):
        """Run spam loop for specified duration."""
        end_time = time.time() + duration

        while self.running and time.time() < end_time:
            try:
                if mode == "post":
                    self.spam_post()
                elif mode == "vote":
                    self.spam_vote()
                elif mode == "comment":
                    self.spam_comment()
                else:  # mixed
                    choice = random.random()
                    if choice < 0.5:
                        self.spam_post()
                    elif choice < 0.8:
                        self.spam_vote()
                    else:
                        self.spam_comment()
            except Exception:
                pass

    def stop(self):
        self.running = False


def print_live_stats(stats: SpamStats, interval: float = 2.0, stop_event: threading.Event = None):
    """Print live statistics."""
    while not (stop_event and stop_event.is_set()):
        time.sleep(interval)
        elapsed = time.time() - stats.start_time
        retry_str = f" | Retry: {stats.retries}" if stats.retries else ""
        print(
            f"\r[{elapsed:.0f}s] "
            f"TX: {stats.total_requests} | "
            f"OK: {stats.successful} | "
            f"Fail: {stats.failed}{retry_str} | "
            f"TPS: {stats.get_rps():.1f} | "
            f"Lat: {stats.get_avg_latency()*1000:.0f}ms | "
            f"PoW: {stats.pow_computed}",
            end="",
            flush=True,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirage Blockchain Spam Attack - floods chain with transactions")
    parser.add_argument("--backend", default=DEFAULT_BACKEND, help=f"Backend URL (default: {DEFAULT_BACKEND})")
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS, help=f"Number of workers (default: {DEFAULT_WORKERS})"
    )
    parser.add_argument(
        "--duration", type=int, default=DEFAULT_DURATION, help=f"Duration in seconds (default: {DEFAULT_DURATION})"
    )
    parser.add_argument(
        "--mode",
        choices=["mixed", "post", "vote", "comment"],
        default="mixed",
        help="Spam mode: mixed (50%% posts, 30%% votes, 20%% comments), post, vote, or comment (default: mixed)",
    )
    parser.add_argument("--seed", default=None, help="Base seed for workers (optional)")
    args = parser.parse_args()

    backend = str(args.backend).rstrip("/")
    num_workers = args.workers
    duration = args.duration
    mode = args.mode

    print("=" * 60)
    print("MIRAGE BLOCKCHAIN SPAM ATTACK")
    print("=" * 60)
    print(f"Backend: {backend}")
    print(f"Workers: {num_workers}")
    print(f"Duration: {duration}s")
    print(f"Mode: {mode}")
    print("=" * 60)

    # Test connection
    try:
        last, diff, base_bits = _fetch_params(backend)
        print(f"Connected! Block: {last[:16]}... | Difficulty: {diff} | BaseBits: {base_bits}")
    except Exception as e:
        print(f"ERROR: Cannot connect to backend: {e}")
        return 1

    # Initialize stats
    stats = SpamStats()
    stats.start_time = time.time()

    # Create workers
    workers = []
    for i in range(num_workers):
        seed = f"{args.seed} {i}" if args.seed else None
        worker = SpamWorker(i, backend, stats, seed)
        workers.append(worker)
        print(f"Worker {i}: {worker.address}")

    print("=" * 60)
    print("STARTING ATTACK...")
    print("=" * 60)

    # Start live stats printer
    stop_event = threading.Event()
    stats_thread = threading.Thread(target=print_live_stats, args=(stats, 2.0, stop_event), daemon=True)
    stats_thread.start()

    # Run workers in thread pool
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(worker.run, duration, mode) for worker in workers]

        try:
            # Wait for duration, then signal workers to stop
            time.sleep(duration)
            print("\n\nDuration complete, signaling workers to stop...")
            for worker in workers:
                worker.stop()

            # Give workers up to 3 minutes to finish current PoW operation
            print("Waiting for workers to finish current operations (up to 3 min)...")
            done_count = 0
            for future in as_completed(futures, timeout=180):
                try:
                    future.result()
                    done_count += 1
                except Exception:
                    done_count += 1

        except KeyboardInterrupt:
            print("\n\nInterrupted! Signaling workers to stop...")
            for worker in workers:
                worker.stop()
            # Still wait for clean shutdown
            print("Waiting for workers to finish (Ctrl+C again to force)...")
            try:
                for future in as_completed(futures, timeout=60):
                    try:
                        future.result()
                    except Exception:
                        pass
            except (KeyboardInterrupt, TimeoutError):
                print("Force stopping...")

        except TimeoutError:
            # This is fine - some workers may still be doing PoW
            print("\nSome workers still computing PoW, continuing to results...")

    # Stop stats printer
    stop_event.set()
    time.sleep(0.5)

    # Print final results
    elapsed = time.time() - stats.start_time
    print("\n")
    print("=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    print(f"Duration: {elapsed:.1f}s")
    print(f"Total Transactions: {stats.total_requests}")
    print(f"Successful: {stats.successful}")
    print(f"Failed: {stats.failed}")
    if stats.retries:
        print(f"Difficulty Retries: {stats.retries} (not counted as failures)")
    print(f"Success Rate: {(stats.successful / max(stats.total_requests, 1)) * 100:.1f}%")
    print(f"Transactions/sec: {stats.get_rps():.2f}")
    print(f"PoW Computed: {stats.pow_computed}")
    print(f"Avg Latency: {stats.get_avg_latency()*1000:.1f}ms")
    print(f"P99 Latency: {stats.get_p99_latency()*1000:.1f}ms")

    # Per-difficulty PoW timing breakdown
    stats.print_pow_summary()

    print("\nStatus Codes:")
    for code, count in sorted(stats.status_codes.items()):
        print(f"  {code}: {count}")

    if stats.error_types:
        print("\nTop Errors:")
        sorted_errors = sorted(stats.error_types.items(), key=lambda x: -x[1])[:10]
        for error, count in sorted_errors:
            print(f"  [{count}] {error}")

    print("=" * 60)

    # Exit 0 as long as *some* transactions succeeded — difficulty increases cause
    # expected transient failures during param refresh, which are not real errors.
    return 0 if stats.successful > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
