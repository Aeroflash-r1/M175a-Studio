"""mDNS/DNS-SD advertising — this is what makes the phone "see" the printer.

Registers, on every LAN IP + the Mobile-Hotspot IP:
  _ipp._tcp      -> printing (Android 8+ native / Mopria)
  _scanner._tcp  -> eSCL/AirScan scanning (Mopria scan, iOS too)
  _uscan._tcp    -> eSCL (older alias)
  _http._tcp     -> bridge web UI
"""
import socket
import threading

from .config import load
from .util.netinfo import local_ipv4s

_stop = threading.Event()
_registrar = None


def _txt(d):
    return {k: str(v) for k, v in d.items()}


def start(cfg, port, scan_caps=None):
    global _registrar
    from zeroconf import Zeroconf, ServiceInfo

    zc = Zeroconf()
    _registrar = zc
    name = cfg.get("device_name", "HP Color LaserJet MFP M175a")
    uuid = cfg.get("device_uuid", "ce1f6a20-0002-3d17-8d3a-6d31373561")
    host = socket.gethostname() + ".local."
    ips = [socket.inet_aton(ip) for ip, _ in local_ipv4s()]
    if not ips:
        ips = [socket.inet_aton("127.0.0.1")]

    services = [
        ("_ipp._tcp.local.", name + "._ipp",
         _txt({"txtvers": "1", "qtotal": "1", "rp": "ipp/print",
               "ty": name, "note": "M175 Bridge", "uuid": uuid,
               "pdl": "application/pdf",
               "Color": "T", "Duplex": "F", "Scan": "T"})),
        ("_scanner._tcp.local.", name + "._scanner",
         _txt({"txtvers": "1", "ty": name, "uuid": uuid, "rp": "eSCL",
               "pdl": "image/jpeg", "Color": "T", "Duplex": "F",
               "is": "platen"})),
        ("_uscan._tcp.local.", name + "._uscan",
         _txt({"txtvers": "1", "ty": name, "uuid": uuid, "rp": "eSCL",
               "pdl": "image/jpeg"})),
        ("_http._tcp.local.", name + " Web UI._http",
         _txt({"path": "/", "ty": name + " (M175 Bridge)"})),
    ]
    for stype, sname, txt in services:
        info = ServiceInfo(
            stype, sname + "." + stype,
            addresses=ips, port=port,
            properties=txt, server=host, weight=0, priority=0,
        )
        try:
            zc.register_service(info)
            print(f"  [mdns] advertised {stype} as '{sname}'")
        except Exception as e:
            print(f"  [mdns] FAILED {stype}: {e}")


def stop():
    global _registrar
    if _registrar:
        try:
            _registrar.close()
        except Exception:
            pass
        _registrar = None
