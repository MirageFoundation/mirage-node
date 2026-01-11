#!/usr/bin/env python3
"""
Mirage Configuration Management

Centralized configuration loading and management for all Mirage components.
"""
import os
import json
import tomllib as toml
from pathlib import Path
from typing import Dict, Any, Optional


class MirageConfig:
    """Central configuration manager for Mirage blockchain."""

    def __init__(self, config_path: Optional[str] = None):
        """Initialize configuration by aggregating node HOME config files.

        We favor the node's HOME config directory (client.toml, app.toml, config.toml, genesis.json)
        as the single source of truth. A separate YAML file is no longer required.
        """
        self.config_path = Path(config_path) if config_path else None
        self._config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """Load configuration by reading node HOME config files into sections."""
        home_base = str(Path.home() / ".mirage")
        home = os.path.join(home_base, "main")
        cfg_dir = os.path.join(home, "config")

        def _read_toml(path: str) -> Dict[str, Any]:
            if not os.path.isfile(path):
                raise FileNotFoundError(path)
            try:
                with open(path, "rb") as f:
                    return toml.load(f)
            except Exception as e:
                raise ValueError(f"failed to parse toml: {path}: {e}")

        def _read_json(path: str) -> Dict[str, Any]:
            if not os.path.isfile(path):
                raise FileNotFoundError(path)
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                raise ValueError(f"failed to parse json: {path}: {e}")

        client_toml = _read_toml(os.path.join(cfg_dir, "client.toml"))
        app_toml = _read_toml(os.path.join(cfg_dir, "app.toml"))
        comet_toml = _read_toml(os.path.join(cfg_dir, "config.toml"))
        genesis = _read_json(os.path.join(cfg_dir, "genesis.json"))

        # Derive ports
        def _port_from_laddr_strict(addr: str) -> int:
            s = str(addr or "")
            if ":" not in s:
                raise ValueError(f"invalid laddr: {s}")
            try:
                return int(s.rsplit(":", 1)[-1])
            except Exception:
                raise ValueError(f"invalid laddr port: {s}")

        rpc_laddr = (comet_toml.get("rpc") or {}).get("laddr")
        if not rpc_laddr:
            raise KeyError("config.toml: [rpc].laddr missing")
        rpc_port = _port_from_laddr_strict(rpc_laddr)

        p2p_laddr = (comet_toml.get("p2p") or {}).get("laddr")
        if not p2p_laddr:
            raise KeyError("config.toml: [p2p].laddr missing")
        p2p_port = _port_from_laddr_strict(p2p_laddr)

        grpc_addr = (app_toml.get("grpc") or {}).get("address")
        if not grpc_addr:
            raise KeyError("app.toml: [grpc].address missing")
        try:
            grpc_port = int(str(grpc_addr).rsplit(":", 1)[-1])
        except Exception:
            raise ValueError(f"invalid grpc address: {grpc_addr}")

        api_addr = (app_toml.get("api") or {}).get("address")
        if not api_addr:
            raise KeyError("app.toml: [api].address missing")
        try:
            rest_port = int(str(api_addr).rsplit(":", 1)[-1])
        except Exception:
            raise ValueError(f"invalid api address: {api_addr}")

        # Economics
        mg = app_toml.get("minimum-gas-prices") or app_toml.get("minimum_gas_prices")
        if not mg or not str(mg).strip():
            raise KeyError("app.toml: minimum-gas-prices missing or empty")
        min_gas = str(mg)
        bond_denom = (((genesis.get("app_state") or {}).get("staking") or {}).get("params") or {}).get("bond_denom")
        if not bond_denom:
            raise KeyError("genesis.json: app_state.staking.params.bond_denom missing")
        mint_denom = "umirage"

        # Consensus
        tc = (comet_toml.get("consensus") or {}).get("timeout_commit")
        if not tc:
            raise KeyError("config.toml: [consensus].timeout_commit missing")
        timeout_commit = str(tc)

        # Chain
        chain_id_val = client_toml.get("chain-id")
        if not chain_id_val:
            raise KeyError("client.toml: chain-id missing")
        chain_id = str(chain_id_val)
        keyring_backend_val = client_toml.get("keyring-backend")
        if not keyring_backend_val:
            raise KeyError("client.toml: keyring-backend missing")
        keyring_backend = str(keyring_backend_val)

        config: Dict[str, Any] = {
            "chain_id": chain_id,
            "keyring_backend": keyring_backend,
            "ports": {
                "p2p": p2p_port,
                "rpc": rpc_port,
                "rest": rest_port,
                "grpc": grpc_port,
            },
            "consensus": {"timeout_commit": timeout_commit},
            "economics": {
                "bond_denom": bond_denom,
                "mint_denom": mint_denom,
                "gas_price": min_gas,
            },
        }

        return config

    def get(self, *path: str, default: Any = None) -> Any:
        """Get configuration value by path (e.g., get('ports', 'rpc'))."""
        current = self._config
        for key in path:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current

    def get_node_config(self) -> Dict[str, Any]:
        """Return node configuration."""
        home_path = os.path.join(str(Path.home() / ".mirage"), "main")
        p2p = int(self.get("ports", "p2p", default=26656))
        rpc = int(self.get("ports", "rpc", default=26657))
        rest = int(self.get("ports", "rest", default=1317))
        grpc = int(self.get("ports", "grpc", default=9090))

        return {
            "name": "main",
            "home": home_path,
            "ports": {"p2p": p2p, "rpc": rpc, "rest": rest, "grpc": grpc},
            "urls": {"rpc": f"http://127.0.0.1:{rpc}", "rest": f"http://127.0.0.1:{rest}", "grpc": f"127.0.0.1:{grpc}"},
        }

    def get_keyring_backend(self) -> str:
        """Get the keyring backend type."""
        return str(self.get("keyring_backend", default="os"))

    def get_indexer_config(self) -> Dict[str, Any]:
        """Get indexer configuration (derived from node HOME).

        - JSON-RPC/GRPC resolved from node ports
        - Database URL must be provided via MIRAGE_INDEXER_DB_URL (no fallbacks)
        - Enabled defaults to True (override MIRAGE_INDEXER_ENABLED)
        """
        # Resolve ports directly from loaded config
        rpc = int(self.get("ports", "rpc", default=26657))
        grpc = int(self.get("ports", "grpc", default=9090))

        enabled_env = os.environ.get("MIRAGE_INDEXER_ENABLED")
        enabled = True if enabled_env is None else enabled_env.lower() in ("1", "true", "yes")
        db_url = os.environ.get("MIRAGE_INDEXER_DB_URL", "").strip()
        if not db_url:
            raise RuntimeError("MIRAGE_INDEXER_DB_URL is required (no fallbacks)")
        return {
            "enabled": enabled,
            "jsonrpc_url": f"http://127.0.0.1:{rpc}",
            "grpc_url": f"127.0.0.1:{grpc}",
            "database_url": db_url,
            "reconnect": {"initial_delay": 1, "max_delay": 60, "max_retries": -1},
        }


# Global configuration instance
_config_instance: Optional[MirageConfig] = None


def get_config(config_path: Optional[str] = None) -> MirageConfig:
    """Get global configuration instance."""
    global _config_instance
    if _config_instance is None or config_path is not None:
        _config_instance = MirageConfig(config_path)
    return _config_instance
