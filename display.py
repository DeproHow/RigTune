"""Monitor detection and refresh-rate / resolution changes via the Win32 API."""
import ctypes
from ctypes import wintypes

from .win import IS_WINDOWS

ENUM_CURRENT_SETTINGS = -1
DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x1
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x4
DM_BITSPERPEL = 0x40000
DM_PELSWIDTH = 0x80000
DM_PELSHEIGHT = 0x100000
DM_DISPLAYFREQUENCY = 0x400000
CDS_UPDATEREGISTRY = 0x1
CDS_TEST = 0x2
DISP_CHANGE_SUCCESSFUL = 0


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("dmPositionX", wintypes.LONG),
        ("dmPositionY", wintypes.LONG),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


def _new_devmode():
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    return dm


def list_monitors():
    """Return a list of active monitors with current + available modes."""
    if not IS_WINDOWS:
        return []
    user32 = ctypes.windll.user32
    monitors = []
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(dd)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        i += 1
        if not dd.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            continue
        source = dd.DeviceName
        mon = DISPLAY_DEVICEW()
        mon.cb = ctypes.sizeof(mon)
        mon_name = "Monitor"
        if user32.EnumDisplayDevicesW(source, 0, ctypes.byref(mon), 0):
            mon_name = mon.DeviceString or mon_name

        cur = _new_devmode()
        if not user32.EnumDisplaySettingsW(source, ENUM_CURRENT_SETTINGS, ctypes.byref(cur)):
            continue
        modes = set()
        j = 0
        while True:
            dm = _new_devmode()
            if not user32.EnumDisplaySettingsW(source, j, ctypes.byref(dm)):
                break
            j += 1
            if dm.dmBitsPerPel >= 24:
                modes.add((dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency))
        if not modes:
            continue
        cw, ch, cf = cur.dmPelsWidth, cur.dmPelsHeight, cur.dmDisplayFrequency
        native = max(modes, key=lambda m: (m[0] * m[1], m[2]))
        nw, nh = native[0], native[1]
        max_hz_cur = max(m[2] for m in modes if m[0] == cw and m[1] == ch) if any(
            m[0] == cw and m[1] == ch for m in modes) else cf
        max_hz_native = max(m[2] for m in modes if m[0] == nw and m[1] == nh)
        monitors.append({
            "source": source,
            "name": mon_name,
            "adapter": dd.DeviceString,
            "primary": bool(dd.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE),
            "width": cw, "height": ch, "hz": cf,
            "native_width": nw, "native_height": nh,
            "max_hz_current_res": max_hz_cur,
            "max_hz_native": max_hz_native,
        })
    return monitors


def set_mode(source, width, height, hz):
    """Change a monitor's mode permanently. Returns (ok, message)."""
    if not IS_WINDOWS:
        return False, "Windows only"
    user32 = ctypes.windll.user32
    dm = _new_devmode()
    if not user32.EnumDisplaySettingsW(source, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
        return False, "Couldn't read current display settings"
    dm.dmPelsWidth = width
    dm.dmPelsHeight = height
    dm.dmDisplayFrequency = hz
    dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT | DM_DISPLAYFREQUENCY
    fn = user32.ChangeDisplaySettingsExW
    r = fn(source, ctypes.byref(dm), None, CDS_TEST, None)
    if r != DISP_CHANGE_SUCCESSFUL:
        return False, f"Windows rejected {width}x{height} @ {hz}Hz (code {r})"
    r = fn(source, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None)
    if r != DISP_CHANGE_SUCCESSFUL:
        return False, f"Change failed (code {r})"
    return True, f"Set to {width}x{height} @ {hz}Hz"
