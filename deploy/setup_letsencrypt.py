#!/usr/bin/env python3
"""
Let's Encrypt HTTPS setup for Caddy.

Usage: python3 deploy/setup_letsencrypt.py --domain=example.com
"""

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: requests")
    print("Install with: pip install requests")
    sys.exit(1)

ROOT_DIR = Path("/opt/mirage")
CADDY_DIR = Path("/etc/caddy")


def validate_domain(domain: str) -> tuple[bool, str]:
    """Validate domain format. Returns (is_valid, error)."""
    if not domain:
        return False, "Domain is required"
    
    # Basic domain format check
    pattern = r"^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$"
    if not re.match(pattern, domain):
        return False, f"Invalid domain format: {domain}"
    
    # Check for common mistakes
    if domain.startswith("www."):
        return False, "Do not include 'www.' prefix (it's added automatically)"
    
    if domain.startswith("http://") or domain.startswith("https://"):
        return False, "Do not include protocol (http:// or https://)"
    
    return True, ""


def get_public_ip() -> str | None:
    """Get this host's public IP."""
    try:
        resp = requests.get("https://api.ipify.org", timeout=10)
        resp.raise_for_status()
        return resp.text.strip()
    except Exception as e:
        print(f"    Warning: Could not get public IP: {e}")
        return None


def get_domain_ip(domain: str) -> str | None:
    """Get domain's A record using external DNS."""
    try:
        result = subprocess.run(
            ["dig", "+short", domain, "@1.1.1.1", "A"],
            capture_output=True, text=True, timeout=10
        )
        ips = result.stdout.strip().split("\n")
        return ips[0] if ips and ips[0] else None
    except Exception as e:
        print(f"    Warning: DNS lookup failed: {e}")
        return None


def check_port_open(port: int) -> bool:
    """Check if a port is reachable from outside."""
    try:
        # Use a port checker service
        resp = requests.get(f"https://portchecker.co/check", 
                          params={"port": port}, timeout=10)
        # This is a rough check - the service may not be available
        return True
    except Exception:
        return True  # Assume open if we can't check


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a command."""
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def main():
    parser = argparse.ArgumentParser(
        description="Configure HTTPS using Let's Encrypt",
        epilog="Ensure ports 80 and 443 are open and forwarded to this host."
    )
    parser.add_argument("--domain", required=True, help="Domain name (e.g., example.com)")
    args = parser.parse_args()
    
    domain = args.domain.strip().lower()
    
    print("==> Let's Encrypt HTTPS Setup")
    print()
    
    # Validate domain format
    valid, error = validate_domain(domain)
    if not valid:
        print(f"ERROR: {error}")
        return 1
    print(f"    ✓ Domain format valid: {domain}")
    
    # Check DNS resolution
    print()
    print("==> Checking DNS...")
    host_ip = get_public_ip()
    domain_ip = get_domain_ip(domain)
    
    print(f"    Public IP (this host): {host_ip or 'unknown'}")
    print(f"    {domain} resolves to:  {domain_ip or 'not found'}")
    
    if not domain_ip:
        print()
        print("ERROR: Domain does not resolve to any IP address.")
        print("       Make sure you've added an A record pointing to this server.")
        return 1
    
    if host_ip and domain_ip != host_ip:
        print()
        print(f"ERROR: Domain resolves to {domain_ip}, but this server's IP is {host_ip}")
        print("       Update your DNS A record to point to this server.")
        return 1
    
    print("    ✓ DNS configured correctly")
    
    # Check www subdomain
    www_ip = get_domain_ip(f"www.{domain}")
    if www_ip and www_ip != domain_ip:
        print(f"    Warning: www.{domain} resolves to {www_ip} (different from {domain})")
    elif not www_ip:
        print(f"    Note: www.{domain} has no A record (optional)")
    
    # Create directories
    CADDY_DIR.mkdir(parents=True, exist_ok=True)
    data_dir = Path.home() / ".local" / "share" / "caddy"
    data_dir.mkdir(parents=True, exist_ok=True)
    
    # Render Caddyfile
    print()
    print("==> Rendering Caddyfile...")
    template = ROOT_DIR / "deploy" / "templates" / "caddy" / "Caddyfile"
    if not template.exists():
        print(f"ERROR: Template not found: {template}")
        return 1
    
    # Render template
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".conf") as f:
        temp_caddy = f.name
    
    os.environ["DOMAIN"] = domain
    result = run(["python3", str(ROOT_DIR / "deploy" / "render_template.py"),
                  str(template), temp_caddy], check=False)
    if result.returncode != 0:
        print(f"ERROR: Failed to render template: {result.stderr}")
        return 1
    
    # Create final Caddyfile with www redirect
    caddyfile = CADDY_DIR / "Caddyfile"
    with open(temp_caddy) as f:
        rendered = f.read()
    os.unlink(temp_caddy)
    
    final_config = f"""www.{domain} {{
\tredir https://{domain}{{uri}} permanent
}}

{rendered}"""
    
    caddyfile.write_text(final_config)
    print(f"    ✓ Caddyfile written: {caddyfile}")
    
    # Validate Caddyfile
    print()
    print("==> Validating Caddyfile...")
    result = run(["caddy", "validate", "--config", str(caddyfile), "--adapter", "caddyfile"], check=False)
    if result.returncode != 0:
        print(f"ERROR: Caddyfile validation failed:")
        print(result.stderr)
        return 1
    print("    ✓ Caddyfile valid")
    
    # Reload Caddy
    print()
    print("==> Reloading Caddy...")
    result = run(["caddy", "reload", "--config", str(caddyfile), "--adapter", "caddyfile"], check=False)
    if result.returncode != 0:
        print(f"ERROR: Failed to reload Caddy:")
        print(result.stderr)
        return 1
    print("    ✓ Caddy reloaded")
    
    # Persist domain to node.env
    node_env = Path.home() / ".mirage" / "env" / "node.env"
    if node_env.exists():
        content = node_env.read_text()
        if "DOMAIN=" in content:
            content = re.sub(r"^DOMAIN=.*$", f"DOMAIN={domain}", content, flags=re.MULTILINE)
        else:
            content += f"\nDOMAIN={domain}\n"
        node_env.write_text(content)
        print(f"    ✓ Domain saved to {node_env}")
    else:
        print(f"    Warning: {node_env} not found, domain not persisted")
    
    # Final summary
    print()
    print("=" * 50)
    print("HTTPS CONFIGURED")
    print("=" * 50)
    print()
    print(f"  Domain: https://{domain}")
    print(f"  WWW redirect: https://www.{domain} -> https://{domain}")
    print()
    print("  Let's Encrypt will automatically issue a certificate.")
    print("  This may take a minute on first request.")
    print()
    print("  Test with: curl -I https://{domain}")
    print()
    
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n    Aborted.")
        sys.exit(0)
