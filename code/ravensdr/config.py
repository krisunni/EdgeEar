# Persistent configuration for ravenSDR
#
# Reads from config.json with env var fallback for backwards compatibility.
# Supports runtime changes via save_config().

import json
import logging
import os
import tempfile

log = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_CONFIG = {
    "secondary_dongle": {
        "enabled": False,
        "task": None,       # "adsb", "meteor", "wefax", or None
        "device_index": 1,
    },
}


def load_config():
    """Load config from config.json, falling back to env vars then defaults.

    Precedence: config.json > env vars > defaults
    """
    config = _deep_copy(DEFAULT_CONFIG)

    # Try loading from file
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                file_config = json.load(f)
            _merge(config, file_config)
            log.info("Config loaded from %s", CONFIG_FILE)
            return config
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Failed to load config.json: %s — using env vars", e)

    # Fall back to env vars (backwards compatible)
    adsb_dual = os.environ.get("ADSB_DUAL_DONGLE", "false").lower() == "true"
    meteor_dual = os.environ.get("METEOR_DUAL_DONGLE", "false").lower() == "true"
    meteor_enabled = os.environ.get("METEOR_ENABLED", "false").lower() == "true"

    if adsb_dual:
        config["secondary_dongle"]["enabled"] = True
        config["secondary_dongle"]["task"] = "adsb"
    elif meteor_dual and meteor_enabled:
        config["secondary_dongle"]["enabled"] = True
        config["secondary_dongle"]["task"] = "meteor"

    return config


def save_config(config):
    """Save config to config.json atomically."""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    try:
        fd, tmp_path = tempfile.mkstemp(
            dir=os.path.dirname(CONFIG_FILE), suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(config, f, indent=2)
            os.replace(tmp_path, CONFIG_FILE)
            log.info("Config saved to %s", CONFIG_FILE)
        except Exception:
            os.unlink(tmp_path)
            raise
    except OSError as e:
        log.error("Failed to save config: %s", e)


def get_secondary_task(config=None):
    """Get the configured secondary dongle task.

    Returns: "adsb", "meteor", "wefax", or None
    """
    if config is None:
        config = load_config()
    sec = config.get("secondary_dongle", {})
    if sec.get("enabled") and sec.get("task"):
        return sec["task"]
    return None


def get_secondary_device_index(config=None):
    """Get the device index for the secondary dongle."""
    if config is None:
        config = load_config()
    return config.get("secondary_dongle", {}).get("device_index", 1)


def set_secondary_task(task):
    """Set the secondary dongle task and save config.

    Args:
        task: "adsb", "meteor", "wefax", or None (to disable)

    Returns:
        Updated config dict
    """
    config = load_config()
    if task and task in ("adsb", "meteor", "wefax"):
        config["secondary_dongle"]["enabled"] = True
        config["secondary_dongle"]["task"] = task
    else:
        config["secondary_dongle"]["enabled"] = False
        config["secondary_dongle"]["task"] = None
    save_config(config)
    return config


def _deep_copy(d):
    """Simple deep copy for nested dicts."""
    return json.loads(json.dumps(d))


def _merge(base, override):
    """Merge override dict into base dict recursively."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _merge(base[key], value)
        else:
            base[key] = value
