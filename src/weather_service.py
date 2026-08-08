#!/usr/bin/env python3
"""
Simple weather service to fetch METARs for specified stations.

This module fetches METAR observations from the FAA/NWS aviationweather ADDs
API and returns a normalized dictionary per station including a UTC
`fetched_at` timestamp. It is intentionally lightweight (no caching) so it
can be extended later with adapters, caching, or additional providers.

Usage:
    from weather_service import fetch_metars
    res = fetch_metars(["BFI", "RNT"])  # returns dict
"""

from datetime import datetime, timezone
import re
import requests
from typing import Dict, List, Any, Union
import json
import os
from pathlib import Path

ADDS_METAR_ENDPOINT = (
    "https://aviationweather.gov/api/data/metar"
)


def _iso_now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_metar_xml(xml_text: str) -> List[Dict[str, Any]]:
    root = ET.fromstring(xml_text)
    results = []
    for metar in root.findall('.//METAR'):
        entry: Dict[str, Any] = {}
        # simple text fields
        for tag in (
            'raw_text',
            'station_id',
            'observation_time',
            'temp_c',
            'wind_dir_degrees',
            'wind_speed_kt',
            'wind_gust_kt',
            'visibility_statute_mi',
        ):
            el = metar.find(tag)
            if el is not None and el.text is not None:
                entry[tag] = el.text

        # sky_condition elements (may be multiple) -> list
        skies = []
        for sky in metar.findall('sky_condition'):
            attrib = sky.attrib.copy()
            if attrib:
                skies.append(attrib)
        if skies:
            entry['sky_condition'] = skies

        results.append(entry)
    return results


def _extract_wind_from_metar(metar_text: str) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    wind_match = re.search(r"\b(\d{3})(\d{2,3})(G(\d{2,3}))?KT\b", metar_text)
    if wind_match:
        result['wdir'] = int(wind_match.group(1))
        result['wspd'] = int(wind_match.group(2))
        if wind_match.group(4):
            result['wgst'] = int(wind_match.group(4))
    vis_match = re.search(r"\b(\d{1,2}(?:\.\d+|/\d+)?)SM\b", metar_text)
    if vis_match:
        vis_str = vis_match.group(1)
        try:
            if '/' in vis_str:
                num, denom = vis_str.split('/')
                result['visib'] = float(num) / float(denom)
            else:
                result['visib'] = float(vis_str)
        except Exception:
            pass
    ceiling = None
    for sky_match in re.finditer(r"\b(BKN|OVC|VV)(\d{3})\b", metar_text):
        try:
            height = int(sky_match.group(2)) * 100
            if ceiling is None or height < ceiling:
                ceiling = height
        except Exception:
            pass
    if ceiling is not None:
        result['ceiling_ft'] = ceiling
    if 'LTG' in metar_text:
        result['lightning'] = 1
    return result


def fetch_metars(stations: List[str], hours_before_now: int = 2, timeout: int = 10) -> Dict[str, Any]:
    """
    Fetch METARs for the given station IDs and return a mapping.

    Returns a dict with keys:
      - `stations`: mapping station -> parsed METAR dict (or None)
      - `fetched_at`: ISO UTC timestamp when the API was called
      - `source_url`: the effective request URL
      - `error`: optional error string when request/parse failed
    """
    fetched_at = _iso_now_utc()
    # Use the documented JSON API endpoint; supply `ids` parameter and format=json
    params = {
        'ids': ','.join(stations),
        'format': 'json',
    }
    try:
        resp = requests.get(ADDS_METAR_ENDPOINT, params=params, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        return {
            'stations': {s: None for s in stations},
            'fetched_at': fetched_at,
            'source_url': resp.url if 'resp' in locals() else ADDS_METAR_ENDPOINT,
            'error': str(e),
        }

    # parse JSON response (expected list of station objects)
    try:
        data = resp.json()
    except Exception as e:
        return {
            'stations': {s: None for s in stations},
            'fetched_at': fetched_at,
            'source_url': resp.url,
            'error': f'JSON parse error: {e}',
        }

    station_map: Dict[str, Any] = {s: None for s in stations}
    if isinstance(data, dict) and 'errors' in data:
        # some endpoints return an error object
        return {
            'stations': station_map,
            'fetched_at': fetched_at,
            'source_url': resp.url,
            'error': data.get('errors'),
        }

    if isinstance(data, list):
        for raw_entry in data:
            entry = dict(raw_entry)
            sid = entry.get('icaoId') or entry.get('station') or entry.get('station_id')
            if sid:
                # normalize raw METAR text into a consistent single-line field
                raw = entry.get('rawOb') or entry.get('raw_text') or entry.get('raw') or ''
                if isinstance(raw, str):
                    metar_text = ' '.join(raw.split())
                else:
                    metar_text = ''
                entry['metar'] = metar_text
                # remove the rawOb/raw_text/raw field to avoid duplication
                for k in ('rawOb', 'raw_text', 'raw'):
                    if k in entry:
                        del entry[k]

                # extract altimeter in A#### form from the raw METAR if present
                altimeter = None
                m = re.search(r"\bA(\d{3,4})\b", metar_text)
                if m:
                    digits = m.group(1)
                    if len(digits) == 4:
                        altimeter = float(digits[:-2] + '.' + digits[-2:])
                    elif len(digits) == 3:
                        altimeter = float(digits[:-2] + '.' + digits[-2:])
                if altimeter is not None:
                    entry['altimeter'] = altimeter

                # parse wind/visibility/ceiling/lightning from raw METAR text
                parsed = _extract_wind_from_metar(metar_text)
                entry.update(parsed)

                entry['lightning'] = 1 if entry.get('lightning') == 1 else 0
                entry['windspeed_25kts'] = 1 if (entry.get('wspd') is not None and float(entry['wspd']) > 25) else 0
                entry['windgusts_25kts'] = 1 if (entry.get('wgst') is not None and float(entry['wgst']) > 25) else 0

                entry['low_visibility'] = 1 if (entry.get('visib') is not None and float(entry['visib']) < 1.0) else 0
                entry['low_ceiling'] = 1 if (entry.get('ceiling_ft') is not None and entry['ceiling_ft'] < 1000) else 0

                entry['available'] = not any(
                    entry.get(flag) == 1 for flag in [
                        'lightning',
                        'windspeed_25kts',
                        'windgusts_25kts',
                        'low_ceiling',
                        'low_visibility',
                    ]
                )

                station_map[sid] = entry
    else:
        # unexpected shape
        return {
            'stations': station_map,
            'fetched_at': fetched_at,
            'source_url': resp.url,
            'error': 'unexpected JSON shape',
        }

    return {
        'stations': station_map,
        'fetched_at': fetched_at,
        'source_url': resp.url,
    }


def _sanitize_filename(s: str) -> str:
    return s.replace(":", "-")


def save_metars(result: Dict[str, Any], out_dir: Union[str, Path] = "output/weather") -> Path:
    """Save the METAR result dict to `out_dir` as a timestamped JSON file.

    Returns the path to the written file.
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    ts = result.get('fetched_at') or _iso_now_utc()
    fname = f"metars_{_sanitize_filename(ts)}.json"
    file_path = out_path / fname
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    return file_path


def fetch_and_store(stations: List[str], out_dir: Union[str, Path] = "output/weather", **kwargs) -> Dict[str, Any]:
    """Fetch METARs and save the response to disk. Returns the result dict and writes file."""
    res = fetch_metars(stations, **kwargs)
    try:
        path = save_metars(res, out_dir=out_dir)
        res['_stored_path'] = str(path)
    except Exception:
        # do not raise on storage failures; return result with no path
        res['_stored_path'] = None
    return res


