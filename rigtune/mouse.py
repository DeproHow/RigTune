"""Mouse acceleration and pointer speed via SystemParametersInfo."""
import ctypes

from .win import IS_WINDOWS

SPI_GETMOUSE = 0x0003
SPI_SETMOUSE = 0x0004
SPI_GETMOUSESPEED = 0x0070
SPI_SETMOUSESPEED = 0x0071
SPIF_UPDATE = 0x01 | 0x02  # update ini + broadcast


def get_accel():
    """Return [threshold1, threshold2, accel] or None."""
    if not IS_WINDOWS:
        return None
    arr = (ctypes.c_int * 3)()
    if ctypes.windll.user32.SystemParametersInfoW(SPI_GETMOUSE, 0, arr, 0):
        return list(arr)
    return None


def set_accel(values):
    arr = (ctypes.c_int * 3)(*values)
    return bool(ctypes.windll.user32.SystemParametersInfoW(SPI_SETMOUSE, 0, arr, SPIF_UPDATE))


def accel_on():
    v = get_accel()
    return None if v is None else v[2] != 0


def get_speed():
    if not IS_WINDOWS:
        return None
    s = ctypes.c_int()
    if ctypes.windll.user32.SystemParametersInfoW(SPI_GETMOUSESPEED, 0, ctypes.byref(s), 0):
        return s.value
    return None


def set_speed(value):
    return bool(ctypes.windll.user32.SystemParametersInfoW(
        SPI_SETMOUSESPEED, 0, ctypes.c_void_p(int(value)), SPIF_UPDATE))
