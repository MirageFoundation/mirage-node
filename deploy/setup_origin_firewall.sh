#!/usr/bin/env bash
# deploy/setup_origin_firewall.sh
#
# Restrict this origin's public HTTPS (:443) to Bunny's edge IPs, so once the
# node's DNS points at Bunny, nobody can bypass the scanning edge (Bunny Shield
# upload scanning) by hitting the origin directly. Uploads, /api, and /chain must
# all arrive through Bunny.
#
# Run as root ON THE HOST, per node, AT CUTOVER (after DNS for this node points
# at Bunny and you've confirmed Bunny->origin works). Idempotent and reversible.
#
# What it does (an nftables table that coexists with UFW):
#   - tcp/443  : ACCEPT only from Bunny edge ranges (IPv4 + IPv6), else DROP.
#   - tcp/80   : left to UFW (open) so Caddy can still answer ACME HTTP-01 for the
#                origin subdomain's TLS cert (origin.<domain> still resolves here).
#   - 22 / 26656 / everything else : untouched (UFW still governs them).
#   - Installs a systemd service (runs at boot — nft rules are NOT persistent
#     across reboots, so without this a reboot would silently reopen :443) plus a
#     daily timer, both re-fetching Bunny's ranges and rebuilding the set, because
#     Bunny's edge IP list changes over time.
#
# Bunny does NOT publish CIDR blocks, only ~1000 individual edge IPs, so UFW
# (one rule per IP) is impractical; an nftables named set handles this cleanly.
#
# Flags:
#   --apply      Fetch Bunny ranges and (re)install the :443 lockdown + timer. (default)
#   --refresh    Re-fetch ranges and reload the set only (used by the timer).
#   --status     Show the current table, sets, and element counts.
#   --unlock     Remove the lockdown table + timer (reopen :443 to all via UFW).
#   -h|--help    This message.

set -euo pipefail

TABLE="mirage_origin"
BUNNY_IPV4_URL="https://api.bunny.net/system/edgeserverlist"
BUNNY_IPV6_URL="https://api.bunny.net/system/edgeserverlist/ipv6"
SELF_PATH="/usr/local/sbin/mirage-origin-firewall.sh"

die() { echo "ERROR: $*" >&2; exit 1; }
say() { echo; echo "==> $*"; }

[[ $EUID -eq 0 ]] || die "must be run as root"

ACTION="apply"
for arg in "$@"; do
    case "$arg" in
        --apply)   ACTION="apply" ;;
        --refresh) ACTION="refresh" ;;
        --status)  ACTION="status" ;;
        --unlock)  ACTION="unlock" ;;
        -h|--help)
            sed -n '2,/^set -euo/p' "$0" | sed -n 's/^# \{0,1\}//p' | sed '$d'
            exit 0 ;;
        *) die "unknown flag: $arg (see --help)" ;;
    esac
done

need() { command -v "$1" >/dev/null 2>&1 || die "missing dependency: $1 (apt-get install $2)"; }
need nft nftables
need curl curl
need jq jq

# Strict charset filters: the fetched lists are embedded in the nft ruleset, so
# anything that isn't a bare IPv4/IPv6 literal is dropped here (defence in depth).
fetch_ipv4() { curl -fsS --max-time 20 "$BUNNY_IPV4_URL" | jq -r '.[]' | grep -E '^[0-9]+(\.[0-9]+){3}$' || true; }
fetch_ipv6() { curl -fsS --max-time 20 "$BUNNY_IPV6_URL" | jq -r '.[]' | grep -E '^[0-9A-Fa-f:]+$' || true; }

# Join lines into a comma-separated nft set element list.
join_set() { paste -sd, - ; }

build_table() {
    say "Fetching Bunny edge IPs"
    local v4 v6 n4 n6
    v4="$(fetch_ipv4)"; v6="$(fetch_ipv6)"
    n4="$(printf '%s\n' "$v4" | grep -c . || true)"
    n6="$(printf '%s\n' "$v6" | grep -c . || true)"
    [[ "$n4" -gt 0 ]] || die "fetched 0 Bunny IPv4 addresses; refusing to lock :443 (would block everything)"
    echo "    Bunny IPv4: $n4   IPv6: $n6"

    local elems4 elems6 ruleset
    elems4="$(printf '%s\n' "$v4" | join_set)"
    elems6="$(printf '%s\n' "$v6" | join_set)"

    say "Installing nftables table '$TABLE' (guards tcp/443)"
    # Build the whole table atomically into a temp file, VALIDATE it (nft -c), and
    # only then apply it: create-if-missing, delete, then recreate fresh in a
    # single transaction. This fully replaces any prior table (no duplicate
    # chains/rules) with zero open window during the swap.
    #
    # The skeleton heredoc interpolates only ${TABLE} (a trusted constant). The
    # fetched Bunny IP lists are appended via printf ARGUMENTS below, never through
    # shell expansion, so a malformed upstream entry can't inject shell or nft.
    ruleset="$(mktemp)"
    # QUOTED heredoc: nothing inside is expanded by the shell, so comments may
    # contain backticks / $(...) and a stray token can never run a command or
    # inject nft. The table name (a trusted constant) is substituted afterward.
    cat > "$ruleset" <<'NFT'
table inet __TABLE__ { }
delete table inet __TABLE__
table inet __TABLE__ {
    set bunny4 {
        type ipv4_addr
        flags interval
    }
    set bunny6 {
        type ipv6_addr
        flags interval
    }

    chain input {
        # Guards :443 that terminates on the host itself. Sits alongside UFW: we
        # ONLY make a decision for tcp/443; everything else falls through to UFW.
        type filter hook input priority -1; policy accept;

        # Allow established/related and loopback so we never break local/return traffic.
        ct state established,related accept
        iif "lo" accept

        # Only Bunny may reach :443.
        tcp dport 443 ip  saddr @bunny4 accept
        tcp dport 443 ip6 saddr @bunny6 accept
        tcp dport 443 drop
    }

    chain forward {
        # The app runs in a Docker container with a published port, so external
        # traffic to :443 is DNAT'd to the container and traverses the *forward*
        # path (Docker's DOCKER-USER/FORWARD rules), never 'input'. This nft hook
        # at priority -1 runs before Docker's iptables FORWARD (priority 0), so it
        # is what actually blocks direct-to-origin hits that bypass Bunny.
        #
        # CRITICAL: only police DNAT'd connections (inbound to the published :443).
        # The container's OWN outbound HTTPS (saddr 172.17.0.x, masqueraded) also
        # crosses this hook with dport 443 — if we dropped that, we'd cut off all
        # outbound HTTPS from the node (Bunny API, push, ACME, ...). `ct status
        # dnat` matches only the inbound published-port flow, so outbound is
        # untouched and falls through to the chain's accept policy.
        type filter hook forward priority -1; policy accept;

        ct state established,related accept

        # Only Bunny may reach the container's published :443.
        ct status dnat tcp dport 443 ip  saddr @bunny4 accept
        ct status dnat tcp dport 443 ip6 saddr @bunny6 accept
        ct status dnat tcp dport 443 drop
    }
}
NFT
    sed -i "s/__TABLE__/${TABLE}/g" "$ruleset"

    # Populate the sets via printf args (data never shell-expanded). nft tolerates
    # the trailing empty `{ }` only when there are elements, so guard each.
    if [[ -n "$elems4" ]]; then
        printf 'add element inet %s bunny4 { %s }\n' "$TABLE" "$elems4" >> "$ruleset"
    fi
    if [[ -n "$elems6" ]]; then
        printf 'add element inet %s bunny6 { %s }\n' "$TABLE" "$elems6" >> "$ruleset"
    fi

    if ! nft -c -f "$ruleset"; then
        rm -f "$ruleset"
        die "nft ruleset failed validation; NOT applying (origin :443 left unchanged)"
    fi
    nft -f "$ruleset"
    rm -f "$ruleset"
    echo "    table installed."
}

apply() {
    build_table
    install_self_and_timer
    say "Done. :443 is now restricted to Bunny edge IPs."
    echo "    Verify Bunny->origin still serves the site, then check: $0 --status"
    echo "    To revert: $0 --unlock"
}

refresh() {
    # Full atomic rebuild of the table. Used by the systemd service at boot (nft
    # rules don't survive reboots) and by the daily timer (Bunny's edge IP list
    # changes over time). Robust whether or not the table already exists.
    build_table
}

install_self_and_timer() {
    say "Installing self-refresh timer (daily)"
    install -m 0755 "$0" "$SELF_PATH"
    cat > /etc/systemd/system/mirage-origin-fw.service <<UNIT
[Unit]
Description=(Re)build Bunny edge IP allowlist for origin :443 firewall
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=${SELF_PATH} --refresh

[Install]
WantedBy=multi-user.target
UNIT
    cat > /etc/systemd/system/mirage-origin-fw.timer <<UNIT
[Unit]
Description=Daily refresh of Bunny edge IP allowlist

[Timer]
OnCalendar=daily
RandomizedDelaySec=1h
Persistent=true

[Install]
WantedBy=timers.target
UNIT
    systemctl daemon-reload
    # Service enabled (runs at boot to rebuild the table, since nft isn't
    # persistent); timer enabled for the daily IP refresh.
    systemctl enable mirage-origin-fw.service >/dev/null
    systemctl enable --now mirage-origin-fw.timer >/dev/null
    echo "    mirage-origin-fw.service (boot) + mirage-origin-fw.timer (daily) enabled."
}

status() {
    echo "== nft table inet ${TABLE} =="
    if nft list table inet "${TABLE}" 2>/dev/null; then
        echo
        echo "bunny4 elements: $(nft list set inet ${TABLE} bunny4 2>/dev/null | grep -oE '[0-9.]+' | grep -c '\.' || echo 0)"
        echo "bunny6 elements: $(nft list set inet ${TABLE} bunny6 2>/dev/null | grep -c ':' || echo 0)"
    else
        echo "(not installed)"
    fi
    echo
    echo "== timer =="
    systemctl list-timers mirage-origin-fw.timer --no-pager 2>/dev/null | sed -n '1,3p' || true
}

unlock() {
    say "Removing origin lockdown"
    nft delete table inet "${TABLE}" 2>/dev/null && echo "    table removed" || echo "    table not present"
    systemctl disable --now mirage-origin-fw.timer >/dev/null 2>&1 || true
    systemctl disable mirage-origin-fw.service >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/mirage-origin-fw.service /etc/systemd/system/mirage-origin-fw.timer "$SELF_PATH"
    systemctl daemon-reload || true
    echo "    :443 is governed by UFW again (open per UFW rules)."
}

case "$ACTION" in
    apply)   apply ;;
    refresh) refresh ;;
    status)  status ;;
    unlock)  unlock ;;
esac
