"""Local network address discovery."""
import socket

def local_ipv4s():
    """Return list of (ip, iface_hint) for this host."""
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append((s.getsockname()[0], "default"))
        s.close()
    except OSError:
        pass
    try:
        host = socket.gethostname()
        for info in socket.getaddrinfo(host, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and all(ip != p for p, _ in ips):
                ips.append((ip, "hostname"))
    except OSError:
        pass
    return ips

def hotspot_ip():
    """Return the Mobile-Hotspot (192.168.137.x) IP if we host one."""
    for ip, _ in local_ipv4s():
        if ip.startswith("192.168.137."):
            return ip
    return None

def primary_ip():
    ips = local_ipv4s()
    return ips[0][0] if ips else "127.0.0.1"
