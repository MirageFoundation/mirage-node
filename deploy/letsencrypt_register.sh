#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<EOF
Usage: secure_domain_register.sh --domain=example.com

Configures Caddy for HTTPS using Let's Encrypt and reloads it.
This script must run inside the container.

Notes:
  - Ensure ports 80 and 443 are open and forwarded to this host.
  - Certificates are persisted in ~/.local/share/caddy (mounted from host).
EOF
}

DOMAIN=""
for arg in "$@"; do
  case "$arg" in
    --domain=*) DOMAIN="${arg#--domain=}" ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $arg" >&2; usage; exit 1 ;;
  esac
done

if [ -z "$DOMAIN" ]; then
  echo "ERROR: --domain is required" >&2
  usage
  exit 1
fi

# Basic domain format validation
if ! echo "$DOMAIN" | grep -Eq '^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$'; then
  echo "ERROR: invalid domain: $DOMAIN" >&2
  exit 1
fi

ROOT_DIR="/opt/mirage"
CADDY_DIR="/etc/caddy"
DATA_DIR="${HOME}/.local/share/caddy"
mkdir -p "$CADDY_DIR" "$DATA_DIR"

echo "==> Checking DNS A record..."
HOST_IP=$(curl -sf https://api.ipify.org)
DOMAIN_IP=$(getent ahostsv4 "$DOMAIN" | awk '{print $1; exit}')
echo "    Public IP (this host): ${HOST_IP}"
echo "    ${DOMAIN} resolves to: ${DOMAIN_IP}"
if [ "$HOST_IP" != "$DOMAIN_IP" ]; then
  echo "ERROR: Domain does not resolve to this host's public IP ($HOST_IP != $DOMAIN_IP)" >&2
  exit 1
fi

echo "==> Rendering Caddyfile for ${DOMAIN}..."
cat > "$CADDY_DIR/Caddyfile" <<EOF
www.$DOMAIN {
	redir https://$DOMAIN{uri} permanent
}

$DOMAIN {
	encode zstd gzip

	handle /api/* {
		reverse_proxy 127.0.0.1:5000
	}

	# Chain RPC (CometBFT) - includes WebSocket at /rpc/websocket
	handle /rpc/* {
		uri strip_prefix /rpc
		reverse_proxy 127.0.0.1:26657
	}

	# Chain REST/LCD (Cosmos SDK)
	handle /lcd/* {
		uri strip_prefix /lcd
		reverse_proxy 127.0.0.1:1317
	}

	handle {
		root * /opt/mirage/web/frontend/build
		try_files {path} /index.html
		file_server
	}
}
EOF

echo "==> Validating Caddyfile..."
if ! caddy validate --config "$CADDY_DIR/Caddyfile" --adapter caddyfile; then
  echo "ERROR: Caddyfile validation failed" >&2
  exit 1
fi

echo "==> Reloading Caddy..."
caddy reload --config "$CADDY_DIR/Caddyfile" --adapter caddyfile

# Persist domain for automatic HTTPS configuration on subsequent deployments
DOMAIN_PERSIST_FILE="${HOME}/.mirage/.domain"
mkdir -p "$(dirname "$DOMAIN_PERSIST_FILE")"
echo "$DOMAIN" > "$DOMAIN_PERSIST_FILE"
echo "==> Domain persisted to $DOMAIN_PERSIST_FILE (will auto-configure HTTPS on future deployments)"

echo "✓ HTTPS configured for $DOMAIN"


