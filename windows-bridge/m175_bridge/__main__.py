"""M175 Bridge — entry point.

    python run.py        (or: python -m m175_bridge)

Serves, on ONE port (default 8080):
  /ipp/print          -> IPP 1.1 printing (Android native / Mopria)
  /eSCL/...           -> eSCL scanning (Mopria scan / AirScan)
  /                   -> status + manual scan web UI
"""
import socket
import subprocess
import time

from . import __version__
from .config import load
from .util.netinfo import primary_ip
from . import mdns_reg
from .httpd import serve, _SCANNER_CACHE
from .usb import spooler_print
from .scan.engine import list_scanners


def _open_firewall(port):
    rule = "M175Bridge"
    subprocess.run(
        ["netsh", "advfirewall", "firewall", "add", "rule",
         "name=" + rule, "dir=in", "action=allow",
         "protocol=TCP", "localport=" + str(port)],
        capture_output=True, timeout=30)


def main():
    cfg = load()
    port = int(cfg.get("http_port", 8080))
    _open_firewall(port)

    print("=" * 62)
    print("  M175 Bridge  v%s" % __version__)
    print("  Android print+scan gateway for HP Color LaserJet MFP M175a")
    print("=" * 62)

    spooler_print.load_pml_findings()   # real toner from USB analysis
    printer = spooler_print.find_printer(cfg)
    if printer:
        print("  [printer] Windows queue found: '%s'" % printer)
    else:
        print("  [printer] !! No Windows printer detected — run the HP")
        print("  [printer]    installer on D:\\ first, then restart this.")
    # WIA probe is slow (up to 20 s) — do it in background so the
    # server binds instantly and phones can connect right away.
    import threading

    def _probe_scanners():
        _SCANNER_CACHE["names"] = list_scanners()

    threading.Thread(target=_probe_scanners, daemon=True).start()
    scanners = _SCANNER_CACHE["names"]
    if scanners:
        print("  [scanner] WIA devices: " +
              "; ".join(n or "WIA device" for _, n in scanners))
    else:
        print("  [scanner] !! No WIA scanner visible (check HP scan driver)")

    httpd = serve(port)
    print("  [http]    serving on port %d" % port)
    print("  [web UI]  http://%s:%d/   (from this PC)" % (primary_ip(), port))

    mdns_reg.start(cfg, port)
    print("  [mdns]    advertising _ipp/_scanner/_uscan — phone: check")
    print("            Settings > Printing, or Mopria Scan app")
    print()
    print("  Ctrl+C to stop.")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        print("\n  shutting down...")
        mdns_reg.stop()
        httpd.shutdown()


if __name__ == "__main__":
    main()
