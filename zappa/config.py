"""
Runtime configuration for the values that used to be hardcoded in
``zappa/core.py`` (supported regions and zip exclusion patterns).

Values are resolved, in order, from:

1. A custom JSON file pointed at by the ``ZAPPA_CONFIG_FILE`` environment
   variable (or a ``zappa_config.json`` in the current working directory).
2. Comma-separated environment variables:
   ``ZAPPA_API_GATEWAY_REGIONS``, ``ZAPPA_LAMBDA_REGIONS`` and
   ``ZAPPA_ZIP_EXCLUDES``.
3. Region data discovered dynamically from the installed botocore service
   definitions (so new AWS regions light up on a ``botocore`` upgrade without
   requiring a new Zappa release). Disable discovery with
   ``ZAPPA_DISABLE_REGION_DISCOVERY=1``.
4. The shipped defaults in ``zappa/zappa_config.json``.

The dynamic lookups are cached on first use; call ``refresh_config()`` to
force a reload (mainly useful in tests).
"""

import json
import os

DEFAULT_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   'zappa_config.json')
CUSTOM_CONFIG_ENV = 'ZAPPA_CONFIG_FILE'
CUSTOM_CONFIG_FILENAME = 'zappa_config.json'

_API_GATEWAY_REGIONS_ENV = 'ZAPPA_API_GATEWAY_REGIONS'
_LAMBDA_REGIONS_ENV = 'ZAPPA_LAMBDA_REGIONS'
_ZIP_EXCLUDES_ENV = 'ZAPPA_ZIP_EXCLUDES'
_DISABLE_DISCOVERY_ENV = 'ZAPPA_DISABLE_REGION_DISCOVERY'

_CONFIG_CACHE = None


def _load_json_config(path):
    """Load a JSON config file, tolerating a missing or malformed custom file."""
    try:
        with open(path, 'r') as config_file:
            data = json.load(config_file)
    except (IOError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_config_files():
    """
    The shipped defaults are always loaded first; a project-level
    ``zappa_config.json`` and a ``ZAPPA_CONFIG_FILE`` override are layered on
    top of them.
    """
    paths = [DEFAULT_CONFIG_FILE]
    cwd_config = os.path.join(os.getcwd(), CUSTOM_CONFIG_FILENAME)
    if os.path.abspath(cwd_config) != os.path.abspath(DEFAULT_CONFIG_FILE):
        paths.append(cwd_config)
    env_config = os.environ.get(CUSTOM_CONFIG_ENV)
    if env_config:
        paths.append(env_config)
    return paths


def _load_raw_config():
    merged = {}
    for path in _find_config_files():
        loaded = _load_json_config(path)
        for key, value in loaded.items():
            if key.startswith('_'):
                continue
            if isinstance(value, list):
                merged[key] = list(value)
            else:
                merged[key] = value
    return merged


def _csv_env(name):
    raw = os.environ.get(name)
    if raw is None:
        return None
    return [item.strip() for item in raw.split(',') if item.strip()]


def _discover_regions(service_name):
    """
    Ask botocore which regions expose ``service_name``. botocore ships the
    endpoint metadata for every partition, so newly launched regions become
    available as soon as botocore is updated.

    Returns ``None`` when discovery is unavailable or explicitly disabled so
    that callers can fall back to the shipped default list.
    """
    if os.environ.get(_DISABLE_DISCOVERY_ENV, '').lower() in ('1', 'true', 'yes'):
        return None
    try:
        import boto3
        session = boto3.session.Session()
        # Query every partition so that aws-cn and aws-us-gov regions are
        # included rather than only the current commercial partition.
        regions = []
        for partition in session.get_available_partitions():
            regions.extend(session.get_available_regions(
                service_name, partition_name=partition,
                allow_non_regional=False
            ))
        return sorted(set(regions))
    except Exception:  # pragma: no cover - botocore missing or API changed.
        return None


def _regions(config_key, env_name, service_name):
    """
    Resolve a region list: env var overrides everything; otherwise the union
    of the configured defaults and any regions botocore knows about.
    """
    env_regions = _csv_env(env_name)
    if env_regions is not None:
        return env_regions

    configured = list(get_config().get(config_key, []))
    discovered = _discover_regions(service_name)
    if discovered:
        known = set(configured)
        configured.extend(region for region in discovered if region not in known)
    return configured


def get_config():
    """Return the merged file/env configuration (cached)."""
    global _CONFIG_CACHE
    if _CONFIG_CACHE is None:
        _CONFIG_CACHE = _load_raw_config()
    return _CONFIG_CACHE


def get_api_gateway_regions():
    return _regions('api_gateway_regions', _API_GATEWAY_REGIONS_ENV, 'apigateway')


def get_lambda_regions():
    return _regions('lambda_regions', _LAMBDA_REGIONS_ENV, 'lambda')


def get_zip_excludes():
    env_excludes = _csv_env(_ZIP_EXCLUDES_ENV)
    if env_excludes is not None:
        return env_excludes
    return list(get_config().get('zip_excludes', []))


def refresh_config():
    """Drop the cached configuration so it is re-read on next access."""
    global _CONFIG_CACHE
    _CONFIG_CACHE = None
