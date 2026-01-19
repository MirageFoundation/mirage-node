"""
Migration: v1.9.0 - P2P rate limiting via iptables

This migration runs on the HOST (not inside Docker) via enable_rate_limiting.sh.
It adds iptables rules to limit connections to port 26656 (P2P).

Rules added:
- Max 5 concurrent connections per IP to port 26656
- Max 10 new connections per minute per IP to port 26656
"""

# NOTE: This migration is executed by deploy/enable_rate_limiting.sh on the HOST,
# not by the container's migration runner. It uses the same .migrations
# tracking file for consistency.

MIGRATION_KEY = "v1_9_0_p2p_rate_limiting"
DESCRIPTION = "P2P rate limiting via iptables (host-side)"


def run(config_dir, logger):
    """
    This function is here for documentation/consistency with other migrations.
    The actual iptables setup runs via enable_rate_limiting.sh on the HOST.
    
    If called inside the container, it will skip (iptables not available).
    """
    import subprocess
    
    # Check if we're inside Docker (iptables won't work)
    if _is_inside_docker():
        logger.info("    Skipping iptables setup (running inside container)")
        logger.info("    This migration runs on HOST via enable_rate_limiting.sh")
        return "skipped (container)"
    
    # Check if iptables is available
    try:
        subprocess.run(["iptables", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        logger.warning("    iptables not found, skipping P2P rate limiting")
        return "skipped (no iptables)"
    
    rules_added = []
    
    # Rule 1: Limit concurrent connections per IP to port 26656
    if not _rule_exists(["-p", "tcp", "--dport", "26656", "-m", "connlimit", 
                         "--connlimit-above", "5", "--connlimit-mask", "32", "-j", "DROP"]):
        _add_rule(["-p", "tcp", "--dport", "26656", "-m", "connlimit",
                   "--connlimit-above", "5", "--connlimit-mask", "32", "-j", "DROP"])
        rules_added.append("connlimit")
        logger.info("    ✓ Added concurrent connection limit (5 per IP)")
    
    # Rule 2: Rate limit new connections - tracking
    if not _rule_exists(["-p", "tcp", "--dport", "26656", "-m", "state", "--state", "NEW",
                         "-m", "recent", "--set", "--name", "P2P_RATELIMIT"]):
        _add_rule(["-p", "tcp", "--dport", "26656", "-m", "state", "--state", "NEW",
                   "-m", "recent", "--set", "--name", "P2P_RATELIMIT"])
    
    # Rule 3: Rate limit new connections - drop
    if not _rule_exists(["-p", "tcp", "--dport", "26656", "-m", "state", "--state", "NEW",
                         "-m", "recent", "--update", "--seconds", "60", "--hitcount", "10",
                         "--name", "P2P_RATELIMIT", "-j", "DROP"]):
        _add_rule(["-p", "tcp", "--dport", "26656", "-m", "state", "--state", "NEW",
                   "-m", "recent", "--update", "--seconds", "60", "--hitcount", "10",
                   "--name", "P2P_RATELIMIT", "-j", "DROP"])
        rules_added.append("ratelimit")
        logger.info("    ✓ Added new connection rate limit (10 per minute per IP)")
    
    # Persist rules
    _persist_rules(logger)
    
    if rules_added:
        return f"added: {', '.join(rules_added)}"
    return "rules already present"


def _is_inside_docker():
    """Check if we're running inside a Docker container."""
    try:
        with open("/proc/1/cgroup", "r") as f:
            return "docker" in f.read()
    except Exception:
        pass
    # Also check for .dockerenv file
    from pathlib import Path
    return Path("/.dockerenv").exists()


def _rule_exists(rule_args):
    """Check if an iptables rule already exists."""
    import subprocess
    try:
        subprocess.run(
            ["iptables", "-C", "INPUT"] + rule_args,
            capture_output=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _add_rule(rule_args):
    """Add an iptables rule."""
    import subprocess
    subprocess.run(
        ["iptables", "-A", "INPUT"] + rule_args,
        check=True
    )


def _persist_rules(logger):
    """Persist iptables rules across reboots."""
    import subprocess
    import shutil
    
    if shutil.which("netfilter-persistent"):
        try:
            subprocess.run(["netfilter-persistent", "save"], capture_output=True, check=True)
            logger.info("    ✓ Rules persisted via netfilter-persistent")
        except subprocess.CalledProcessError:
            pass
    elif shutil.which("iptables-save"):
        try:
            with open("/etc/iptables.rules", "w") as f:
                subprocess.run(["iptables-save"], stdout=f, check=True)
            logger.info("    ✓ Rules saved to /etc/iptables.rules")
        except Exception:
            pass
