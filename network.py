"""Ping / jitter / packet loss test using the Windows ICMP API (no admin,
not affected by Windows language)."""
import ctypes
import socket
import statistics
import struct
import subprocess
import time
from ctypes import wintypes

from .win import IS_WINDOWS


class IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte),
                ("OptionsSize", ctypes.c_ubyte), ("OptionsData", ctypes.c_void_p)]


class ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [("Address", wintypes.ULONG), ("Status", wintypes.ULONG), ("RoundTripTime", wintypes.ULONG),
                ("DataSize", wintypes.USHORT), ("Reserved", wintypes.USHORT), ("Data", ctypes.c_void_p),
                ("Options", IP_OPTION_INFORMATION)]


def _ping_once_win(handle, addr, timeout_ms=1000):
    icmp = ctypes.windll.iphlpapi
    data = b"RigTunePing" * 3
    buf_size = ctypes.sizeof(ICMP_ECHO_REPLY) + len(data) + 8
    buf = ctypes.create_string_buffer(buf_size)
    icmp.IcmpSendEcho.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p, wintypes.WORD,
                                  ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
    n = icmp.IcmpSendEcho(handle, addr, data, len(data), None, buf, buf_size, timeout_ms)
    if n == 0:
        return None
    reply = ICMP_ECHO_REPLY.from_buffer_copy(buf)
    if reply.Status != 0:
        return None
    return float(reply.RoundTripTime)


def ping(host, count=30, interval=0.2, progress=None):
    """Return dict with avg/min/max/jitter/loss or {'error': ...}."""
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        return {"host": host, "error": "Couldn't resolve host (no internet / DNS problem?)"}
    times = []
    if IS_WINDOWS:
        icmp = ctypes.windll.iphlpapi
        icmp.IcmpCreateFile.restype = wintypes.HANDLE
        h = icmp.IcmpCreateFile()
        addr = struct.unpack("<I", socket.inet_aton(ip))[0]
        try:
            for i in range(count):
                times.append(_ping_once_win(h, addr))
                if progress:
                    progress(i + 1, count)
                time.sleep(interval)
        finally:
            icmp.IcmpCloseHandle(wintypes.HANDLE(h))
    else:  # fallback for testing
        for i in range(count):
            r = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, text=True)
            t = None
            if "time=" in r.stdout:
                try:
                    t = float(r.stdout.split("time=")[1].split()[0])
                except ValueError:
                    pass
            times.append(t)
            if progress:
                progress(i + 1, count)
    ok = [t for t in times if t is not None]
    loss = 100 * (len(times) - len(ok)) / len(times) if times else 100
    if not ok:
        return {"host": host, "ip": ip, "error": "No replies (blocked or offline)", "loss": 100}
    jitter = statistics.mean(abs(a - b) for a, b in zip(ok, ok[1:])) if len(ok) > 1 else 0
    return {"host": host, "ip": ip, "avg": statistics.mean(ok), "min": min(ok), "max": max(ok),
            "jitter": jitter, "loss": loss, "sent": len(times)}


def verdict(r):
    if "error" in r:
        return "bad", r["error"]
    notes = []
    st = "good"
    if r["loss"] >= 2:
        st = "bad"
        notes.append(f"{r['loss']:.0f}% packet loss - you'll get rubber-banding. Check cables/Wi-Fi, restart router.")
    if r["jitter"] > 10:
        st = "bad" if r["jitter"] > 25 else ("warn" if st == "good" else st)
        notes.append(f"Jitter {r['jitter']:.1f}ms is high - ping is unstable (often Wi-Fi or someone downloading).")
    if r["avg"] > 80:
        st = "warn" if st == "good" else st
        notes.append(f"Average {r['avg']:.0f}ms - high. Pick closer game servers if possible.")
    if not notes:
        notes.append("Stable connection - nice.")
    return st, " ".join(notes)


DEFAULT_TARGETS = [("Cloudflare", "1.1.1.1"), ("Google", "8.8.8.8")]
