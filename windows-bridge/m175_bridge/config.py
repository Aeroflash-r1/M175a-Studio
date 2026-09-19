"""M175 Bridge — configuration."""
import json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAPTURES = os.path.join(ROOT, "captures")
TMP = os.path.join(ROOT, "tmp")
SCANS = os.path.join(CAPTURES, "scans")
WEB_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "webui", "static")

DEFAULTS = {
    "printer_name": "",          # empty = auto-detect (M175/CM1415/LaserJet)
    "http_port": 8080,           # single port for IPP + eSCL + web UI
    "device_name": "HP Color LaserJet MFP M175a",
    "device_uuid": "ce1f6a20-0002-3d17-8d3a-6d31373561",   # stable, unique-ish
    "scan_dpi": 200,
    "scan_color": "color",       # color | grayscale | binary
    "max_scan_pages": 20,
    "advertise_hotspot": True,   # also announce on 192.168.137.x Mobile-Hotspot
}

def _cfg_path():
    return os.path.join(ROOT, "config.json")

def load():
    cfg = dict(DEFAULTS)
    try:
        with open(_cfg_path(), "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        save(cfg)
    return cfg

def save(cfg):
    try:
        with open(_cfg_path(), "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError as e:
        print("[config] could not save:", e, file=sys.stderr)
