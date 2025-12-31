"""
notam_fetch.py

Fetch NOTAMs from an external API, write run artifacts locally (for traceability),
and transform the response into constraint FeatureCollections using notam_constraints.py.

Security goals:
- Never commit secrets/tokens to git
- Never print Authorization headers / bearer tokens
- Store raw API responses locally for "replay" and evidence
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from notam_constraints import extract_notam_constraints  # same-folder import


# -----------------------------
# Config
# -----------------------------

DEFAULT_RUNS_DIR = Path.home() / ".utm-orchestrator" / "notam_runs"


@dataclass(frozen=True)
class NotamApiConfig:
    base_url: str
    # If your API needs OAuth/token exchange, fill these in.
    auth_url: Optional[str] = None
    client_id_env: str = "NOTAM_CLIENT_ID"
    client_secret_env: str = "NOTAM_CLIENT_SECRET"


# -----------------------------
# Public entrypoint
# -----------------------------

def run_fetch_and_build_constraints(
    config: NotamApiConfig,
    notams_endpoint: str,
    params: Optional[Dict[str, Any]] = None,
    runs_dir: Path = DEFAULT_RUNS_DIR,
) -> Path:
    """
    1) Fetch NOTAMs
    2) Write raw response + request metadata locally
    3) Convert to constraint layers + write them locally

    Returns:
        Path to the created run directory.
    """
    run_dir = _create_run_dir(runs_dir)

    # Fetch (auth optional, depending on your API)
    response_json, request_meta = fetch_notams(config, notams_endpoint, params=params)

    # Record keeping (local only)
    _write_json(run_dir / "request_meta.json", request_meta)
    _write_json(run_dir / "response_raw.json", response_json)

    # Transform into constraint layers
    layers = extract_notam_constraints(response_json)

    # Write outputs
    _write_json(run_dir / "constraints_uas_airspace.geojson", layers["uas_airspace"])
    _write_json(run_dir / "constraints_obstacles.geojson", layers["obstacles"])
    _write_json(run_dir / "constraints_other.geojson", layers["other"])

    return run_dir

def _build_session() -> requests.Session:
    s = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retries))
    s.mount("http://", HTTPAdapter(max_retries=retries))
    return s


# -----------------------------
# Fetching (adjust to your API)
# -----------------------------

def fetch_notams(
    config: NotamApiConfig,
    notams_endpoint: str,
    params: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Fetch NOTAMs from FAA NMS API.

    Returns:
      (response_json, request_meta_redacted)
    """
    url = _join_url(config.base_url, notams_endpoint)

    headers: Dict[str, str] = {
        "Accept": "application/json",
        # REQUIRED by FAA NMS API
        "nmsResponseFormat": "GEOJSON",
        "User-Agent": "UTM-Orchestrator/0.1",
    }

    if config.auth_url:
        token = _get_bearer_token(config)
        headers["Authorization"] = f"Bearer {token}"

    request_meta = {
        "ts_utc": _now_utc_iso(),
        "method": "GET",
        "url": url,
        "params": params or {},
        "headers": _redact_headers(headers),
    }

    session = _build_session()
    resp = session.get(url, headers=headers, params=params, timeout=(10, 30))
    request_meta["status_code"] = resp.status_code

    try:
        data = resp.json()
    except Exception:
        data = {"raw_text": resp.text}

    if not resp.ok:
        request_meta["error"] = {
            "reason": resp.reason,
            "body_excerpt": (resp.text or "")[:500],
        }
    
    # Normalize FAA NMS payload into a FeatureCollection
    data = _normalize_notam_geojson(data)
   
    return data, request_meta


def _get_bearer_token(config: NotamApiConfig) -> Optional[str]:
    """
    Placeholder token exchange for a typical client-credentials flow.
    You'll need to adapt the payload/fields to your API's auth spec.
    """
    client_id = os.getenv(config.client_id_env)
    client_secret = os.getenv(config.client_secret_env)

    if not client_id or not client_secret:
        raise RuntimeError(
            f"Missing env vars for auth. Expected {config.client_id_env} and {config.client_secret_env}."
        )

    # IMPORTANT: never print these, never write them to disk.
    auth_url = config.auth_url
    assert auth_url is not None

    # Typical pattern (may differ for your API):
    payload = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }
    headers = {"Accept": "application/json"}

    resp = requests.post(auth_url, data=payload, headers=headers, timeout=30)
    resp.raise_for_status()
    token_json = resp.json()

    token = token_json.get("access_token") or token_json.get("token")
    if not token:
        raise RuntimeError("Auth succeeded but no access_token found in response.")
    return str(token)


# -----------------------------
# Helpers
# -----------------------------

def _create_run_dir(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)


def _redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    redacted: Dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() in ("authorization", "x-api-key", "api-key"):
            redacted[k] = "***REDACTED***"
        else:
            redacted[k] = v
    return redacted


def _join_url(base: str, path: str) -> str:
    return base.rstrip("/") + "/" + path.lstrip("/")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _normalize_notam_geojson(response_json: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert NMS response payload into a proper GeoJSON FeatureCollection.

    Expected shapes:
      A) {"status":"Success","data":{"geojson":[Feature,...]}}
      B) Already a FeatureCollection
    """
    # Already a FeatureCollection
    if response_json.get("type") == "FeatureCollection":
        return response_json

    features = (
        response_json.get("data", {}).get("geojson")
        or response_json.get("geojson")
        or []
    )

    if isinstance(features, dict) and features.get("type") == "FeatureCollection":
        return features

    if not isinstance(features, list):
        features = []

    return {"type": "FeatureCollection", "features": features}


# -----------------------------
# CLI (optional)
# -----------------------------
if __name__ == "__main__":
    # Example usage (update once you know your real endpoints):
    cfg = NotamApiConfig(
        base_url=os.getenv("NOTAM_BASE_URL", "https://example.com"),
        auth_url=os.getenv("NOTAM_AUTH_URL"),  # optional
    )

    run_dir = run_fetch_and_build_constraints(
        config=cfg,
        notams_endpoint=os.getenv("NOTAM_NOTAMS_ENDPOINT", "/notams"),
        params=None,
    )

    print(f"Wrote run artifacts to: {run_dir}")
