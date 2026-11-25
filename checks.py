"""All scan checks + the PC Score.

Status values:  good | warn | bad | info | skip
Fix strings the UI understands:
   tweak:<id>                       apply a tweak from tweaks.py
   display:<source>|<w>|<h>|<hz>    change a monitor mode
   page:<name>                      jump to a tab (startup, cleanup, boost, network)
   open:<url>                       open a link / ms-settings page
   bios                             restart straight into BIOS
"""
import datetime as dt
import re
import time
from dataclasses import dataclass, field

import psutil

from . import bios_guides, display, games, mouse, startup, sysinfo, tweaks
from .win import IS_WINDOWS, reg_get, reg_key_exists, run


@dataclass
class CheckResult:
    id: str
    category: str
    title: str
    status: str
    summary: str
    detail: str = ""
    weight: int = 5
    fix: str = None
    fix_label: str = "Fix it"
    steps: list = field(default_factory=list)
    links: list = field(default_factory=list)  # (label, url)


def R(*a, **kw):
    return CheckResult(*a, **kw)


def skip(id_, cat, title, why="Couldn't check this on your system"):
    return R(id_, cat, title, "skip", why, weight=0)


def _days_since(date_str):
    try:
        d = dt.datetime.strptime(date_str[:10], "%Y-%m-%d")
        return (dt.datetime.now() - d).days
    except (TypeError, ValueError):
        return None


# =================================================================== DISPLAY
def check_displays(info):
    cat = "Display"
    out = []
    mons = display.list_monitors()
    if not mons:
        return [skip("display", cat, "Monitors")]
    discrete = [g for g in info.get("gpu", []) if sysinfo.is_discrete(g.get("Name"))]
    laptop = sysinfo.is_laptop(info)
    for i, m in enumerate(mons, 1):
        label = f"Monitor {i}" + (" (main)" if m["primary"] else "") + f" - {m['name']}"
        # --- refresh rate
        best_hz = m["max_hz_native"] if (m["width"], m["height"]) == (m["native_width"], m["native_height"]) \
            else m["max_hz_current_res"]
        if m["hz"] < best_hz - 1:
            out.append(R(f"hz{i}", cat, f"{label}: refresh rate", "bad",
                         f"Running at {m['hz']}Hz but it supports {best_hz}Hz!",
                         "This is one of the most common mistakes. You paid for a high refresh monitor and "
                         f"Windows is only using {m['hz']}Hz. Fixing it makes everything smoother instantly.",
                         weight=15, fix=f"display:{m['source']}|{m['width']}|{m['height']}|{best_hz}",
                         fix_label=f"Set to {best_hz}Hz",
                         steps=["Or manually: Settings > System > Display > Advanced display > Choose a refresh rate."]))
        else:
            tip = ""
            if best_hz <= 60 and m["width"] >= 1920:
                tip = ("If your monitor is supposed to be 144Hz+, check you're using a DisplayPort cable "
                       "(or HDMI 2.0/2.1) plugged into the graphics card, and that the monitor's OSD has "
                       "overclock/high refresh enabled.")
            out.append(R(f"hz{i}", cat, f"{label}: refresh rate", "good",
                         f"{m['hz']}Hz - the highest your monitor reports.", tip, weight=15))
        # --- resolution
        if (m["width"], m["height"]) != (m["native_width"], m["native_height"]):
            out.append(R(f"res{i}", cat, f"{label}: resolution", "warn",
                         f"Desktop is {m['width']}x{m['height']}, native is {m['native_width']}x{m['native_height']}.",
                         "Running below native resolution makes Windows blurry. (If you play stretched res on "
                         "purpose, set it in-game instead of on the desktop.)",
                         weight=5,
                         fix=f"display:{m['source']}|{m['native_width']}|{m['native_height']}|{m['max_hz_native']}",
                         fix_label=f"Set {m['native_width']}x{m['native_height']} @ {m['max_hz_native']}Hz"))
        else:
            out.append(R(f"res{i}", cat, f"{label}: resolution", "good",
                         f"Native {m['width']}x{m['height']}.", weight=5))
        # --- plugged into the wrong port
        if discrete and not sysinfo.is_discrete(m["adapter"]):
            if laptop:
                out.append(R(f"port{i}", cat, f"{label}: GPU", "info",
                             f"Driven by {m['adapter']} (normal for laptop screens with switchable graphics).",
                             "Make sure games use the dedicated GPU: Settings > System > Display > Graphics > "
                             "pick the game > High performance. For best FPS, plug an external monitor into "
                             "the laptop port wired to the dedicated GPU (often the HDMI/USB-C with DP).",
                             weight=0, fix="open:ms-settings:display-advancedgraphics", fix_label="Open Graphics settings"))
            elif not m["primary"]:
                out.append(R(f"port{i}", cat, f"{label}: running on integrated graphics", "warn",
                             f"This second screen runs on {m['adapter']} (motherboard port), not your "
                             f"{discrete[0].get('Name')}.",
                             "Some people do this on purpose so Discord/YouTube don't use the main GPU. It works, "
                             "but it can cause stutter, video playback issues and higher idle power. If you didn't "
                             "do it on purpose, plug it into the graphics card instead.", weight=6))
            else:
                out.append(R(f"port{i}", cat, f"{label}: plugged into the wrong port!", "bad",
                             f"This monitor runs on {m['adapter']} (the CPU's built-in graphics), "
                             f"not your {discrete[0].get('Name')}.",
                             "The cable is in the MOTHERBOARD's video port. Move it to the port on the graphics "
                             "card (the horizontal ports lower down on the back of the PC). This can be a massive "
                             "FPS difference.",
                             weight=25, steps=["Shut down the PC.",
                                               "Unplug the monitor cable from the motherboard's HDMI/DP (vertical, near USB ports).",
                                               "Plug it into the graphics card's DisplayPort (horizontal, lower down).",
                                               "Boot up and run the scan again."]))
        elif discrete:
            out.append(R(f"port{i}", cat, f"{label}: GPU", "good",
                         f"Connected to {m['adapter']}.", weight=10))
    if len(mons) > 1:
        rates = {m["hz"] for m in mons}
        if len(rates) > 1:
            out.append(R("multimon", cat, "Multiple monitors at different refresh rates", "info",
                         f"Your monitors run at {', '.join(str(r) + 'Hz' for r in sorted(rates))}.",
                         "This is fine on Windows 11, but video playing on the second screen (YouTube, Twitch, "
                         "Discord streams) can cause micro-stutter in games. If you notice stutter: pause videos "
                         "while gaming, turn off hardware acceleration in Discord/Chrome, or close them with "
                         "Game Boost.", weight=0, fix="page:boost", fix_label="Open Game Boost"))
    return out


# =================================================================== MOUSE
def check_mouse(info):
    cat = "Mouse & Input"
    out = []
    acc = mouse.accel_on()
    if acc is None:
        out.append(skip("accel", cat, "Mouse acceleration"))
    elif acc:
        out.append(R("accel", cat, "Mouse acceleration", "bad", "'Enhance pointer precision' is ON.",
                     "With acceleration, how far your crosshair moves depends on how FAST you move the mouse, "
                     "not just how far. That destroys muscle memory for aiming.",
                     weight=8, fix="tweak:mouse_accel", fix_label="Turn it off"))
    else:
        out.append(R("accel", cat, "Mouse acceleration", "good", "Off - raw 1:1 aim.", weight=8))
    sp = mouse.get_speed()
    if sp is not None:
        if sp != 10:
            out.append(R("mspeed", cat, "Windows pointer speed", "warn", f"Set to {sp}/20 (default is 10).",
                         "Anything other than 10 makes Windows skip or duplicate pixels. Set it to 10 and "
                         "change sensitivity with your mouse DPI or in-game instead.",
                         weight=3, fix="tweak:mouse_speed", fix_label="Set to 10"))
        else:
            out.append(R("mspeed", cat, "Windows pointer speed", "good", "10/20 - perfect.", weight=3))
    flags = reg_get("HKCU", r"Control Panel\Accessibility\StickyKeys", "Flags")
    if flags is not None:
        try:
            on = int(flags) & 4
        except ValueError:
            on = 0
        if on:
            out.append(R("sticky", cat, "Sticky Keys shortcut", "warn",
                         "Pressing Shift 5 times opens the Sticky Keys popup (and minimises your game).",
                         weight=2, fix="tweak:sticky_keys", fix_label="Disable shortcut"))
        else:
            out.append(R("sticky", cat, "Sticky Keys shortcut", "good", "Disabled.", weight=2))
    return out


# =================================================================== RAM
MEM_TYPES = {34: "DDR5", 26: "DDR4", 24: "DDR3", 35: "LPDDR5", 30: "LPDDR4"}


def rated_from_part(part):
    """Guess the kit's rated speed from its part number."""
    part = (part or "").strip().upper()
    if not part:
        return None
    m = re.search(r"KF[45](\d{2})C", part)  # Kingston Fury: KF560C36 -> 6000
    if m:
        return int(m.group(1)) * 100
    nums = [int(n) for n in re.findall(r"(?<!\d)(\d{4})(?!\d)", part)]
    nums = [n for n in nums if 2133 <= n <= 9600]
    return max(nums) if nums else None


def check_ram(info):
    cat = "Memory (RAM)"
    out = []
    ram = info.get("ram", [])
    if not ram:
        return [skip("ram", cat, "RAM")]
    total_gb = sum(int(r.get("Capacity") or 0) for r in ram) / 1024 ** 3
    mtype = MEM_TYPES.get(ram[0].get("SMBIOSMemoryType"), "")
    configured = min(int(r.get("ConfiguredClockSpeed") or 0) for r in ram) or None
    rated_rep = max(int(r.get("Speed") or 0) for r in ram) or None
    rated_part = max((rated_from_part(r.get("PartNumber")) or 0) for r in ram) or None
    rated = max(x for x in (rated_rep, rated_part, 0) if x is not None) or None
    laptop = sysinfo.is_laptop(info)
    board = info.get("board", {})
    vendor = sysinfo.cpu_vendor(info)
    g = bios_guides.guide(board.get("Manufacturer"), board.get("Product"), vendor, mtype or "DDR4")

    # ---------- XMP / EXPO
    xmp_title = f"{g['profile'].split(' ')[0]} memory profile"
    jedec_cap = {"DDR5": 4800, "DDR4": 2666, "DDR3": 1600}.get(mtype, 0)
    if laptop and mtype.startswith("LP"):
        out.append(R("xmp", cat, xmp_title, "info", f"Soldered {mtype} at {configured} MT/s - laptops lock this.", weight=0))
    elif configured and rated and configured < rated * 0.95:
        out.append(R("xmp", cat, xmp_title, "bad",
                     f"Your RAM runs at {configured} MT/s but it's rated for {rated} MT/s. {g['profile']} is OFF.",
                     f"You're leaving free performance on the table - on CPUs like Ryzen 7000/9000 and Intel "
                     f"12th-14th gen this is often 10-20% FPS in CPU-heavy games and fewer stutters. "
                     f"You need to turn on {g['profile']} in the BIOS. It's safe: it's the speed the RAM "
                     f"maker tested and guarantees." + (" (With 4 sticks, some systems need a slightly lower speed to be stable.)" if len(ram) == 4 else "") + f"\n\nDetected board: {board.get('Manufacturer', '?')} "
                     f"{board.get('Product', '')}  |  BIOS key: {g['key']}",
                     weight=15, fix="bios", fix_label="Restart into BIOS now",
                     steps=g["steps"] + ["Back in Windows, run RigTune scan again to confirm."],
                     links=g["links"]))
    elif configured and jedec_cap and configured <= jedec_cap and (not rated or rated <= configured):
        out.append(R("xmp", cat, xmp_title, "warn",
                     f"RAM at {configured} MT/s - that's the default 'safe' speed, so {g['profile']} is probably OFF.",
                     "Windows didn't report the kit's rated speed, so RigTune can't be 100% sure. Check the "
                     "sticker on your RAM or search its part number "
                     f"({(ram[0].get('PartNumber') or '?').strip()}). If it says a higher number (e.g. 6000 / "
                     f"3600), enable {g['profile']} in BIOS.\n\nDetected board: {board.get('Manufacturer', '?')} "
                     f"{board.get('Product', '')}  |  BIOS key: {g['key']}",
                     weight=10, fix="bios", fix_label="Restart into BIOS now",
                     steps=g["steps"], links=g["links"]))
    elif configured:
        out.append(R("xmp", cat, xmp_title, "good",
                     f"RAM running at {configured} MT/s" + (f" (rated {rated})." if rated else "."), weight=15))
    else:
        out.append(skip("xmp", cat, xmp_title))

    # ---------- dual channel
    n = len(ram)

    def chan(r):
        s = f"{r.get('DeviceLocator', '')} {r.get('BankLabel', '')}".upper()
        for pat in (r"CHANNEL\s*([A-D])", r"DIMM[_\s-]?([A-D])\d", r"\b([A-D])[0-2]\b", r"CH(?:ANNEL)?[_\s-]?([A-D])"):
            m = re.search(pat, s)
            if m:
                return m.group(1)
        return None

    chans = [chan(r) for r in ram]
    if n == 1:
        out.append(R("dual", cat, "Dual channel", "bad", "Only 1 RAM stick = single channel.",
                     "Single channel halves your memory bandwidth. In games that's often 10-30% lower FPS and "
                     "worse 1% lows. Buy a matching second stick (same model) or a 2-stick kit." if not laptop else
                     "Laptops with 1 stick run single channel. If there's a free slot, adding a matching stick "
                     "gives a big boost, especially with integrated graphics.", weight=12))
    elif n == 2 and all(chans) and chans[0] == chans[1]:
        out.append(R("dual", cat, "Dual channel", "bad",
                     f"Both sticks are in channel {chans[0]} ({', '.join(r.get('DeviceLocator', '?') for r in ram)}).",
                     "Both sticks are on the same channel, so you're running single channel. Move one stick so "
                     "they're in slots A2 and B2 (usually the 2nd and 4th slot from the CPU). Check your "
                     "motherboard manual.", weight=12,
                     steps=["Shut down and unplug the PC.", "Move the sticks to slots A2 + B2 (2nd and 4th from the CPU).",
                            "Boot and run the scan again."]))
    elif n == 3:
        out.append(R("dual", cat, "Dual channel", "warn", "3 sticks - mismatched, partly single channel.",
                     "Use 2 or 4 identical sticks for full dual channel.", weight=8))
    else:
        out.append(R("dual", cat, "Dual channel", "good",
                     f"{n} sticks in {', '.join(r.get('DeviceLocator', '?') for r in ram)}.", weight=12))
    # ---------- capacity
    if total_gb < 7.5:
        out.append(R("ramsize", cat, "RAM amount", "bad", f"{total_gb:.0f} GB - too little for modern games.",
                     "16 GB is the minimum today, 32 GB is the sweet spot.", weight=8))
    elif total_gb < 15:
        out.append(R("ramsize", cat, "RAM amount", "warn", f"{total_gb:.0f} GB - some new games will stutter.",
                     "Upgrade to 16-32 GB. Close Chrome/Discord while gaming in the meantime.", weight=6))
    else:
        out.append(R("ramsize", cat, "RAM amount", "good", f"{total_gb:.0f} GB.", weight=6))
    # ---------- usage
    vm = psutil.virtual_memory()
    if vm.percent > 70:
        out.append(R("ramuse", cat, "RAM in use right now", "warn",
                     f"{vm.percent:.0f}% used before even launching a game.",
                     "Something is eating your RAM. Use Game Boost to close background apps.",
                     weight=3, fix="page:boost", fix_label="Open Game Boost"))
    else:
        out.append(R("ramuse", cat, "RAM in use right now", "good", f"{vm.percent:.0f}% used.", weight=3))
    return out


# =================================================================== GPU
DRIVER_LINKS = {
    "nvidia": ("Download NVIDIA driver / NVIDIA App", "https://www.nvidia.com/en-us/geforce/drivers/"),
    "amd": ("Download AMD Adrenalin driver", "https://www.amd.com/en/support/download/drivers.html"),
    "intel": ("Download Intel Arc driver", "https://www.intel.com/content/www/us/en/download-center/home.html"),
}


def check_gpu(info):
    cat = "Graphics (GPU)"
    out = []
    gpus = info.get("gpu", [])
    dgpus = [g for g in gpus if sysinfo.is_discrete(g.get("Name"))]
    main = dgpus[0] if dgpus else (gpus[0] if gpus else None)
    if not main:
        return [skip("gpu", cat, "Graphics card")]
    name = main.get("Name", "GPU")
    low = name.lower()
    vk = "nvidia" if ("nvidia" in low or "geforce" in low or "rtx" in low) else "amd" if ("radeon" in low or "amd" in low) else "intel"
    # ---------- driver age
    age = _days_since(main.get("DriverDate"))
    ver = sysinfo.nvidia_version(main.get("DriverVersion")) if vk == "nvidia" else main.get("DriverVersion")
    if age is None:
        out.append(skip("driver", cat, "GPU driver"))
    elif age > 365:
        out.append(R("driver", cat, "GPU driver", "bad", f"{name}: driver {ver} is {age // 30} months old.",
                     "New drivers include performance fixes for recent games. Update it (a clean install is "
                     "best).", weight=8, links=[DRIVER_LINKS[vk]]))
    elif age > 150:
        out.append(R("driver", cat, "GPU driver", "warn", f"{name}: driver {ver} is {age // 30} months old.",
                     "Worth updating, especially if you play new releases.", weight=8, links=[DRIVER_LINKS[vk]]))
    else:
        out.append(R("driver", cat, "GPU driver", "good", f"{name}: driver {ver} ({age} days old).", weight=8,
                     links=[DRIVER_LINKS[vk]]))
    # ---------- HAGS
    hw = reg_get("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
    if dgpus:
        if hw == 2:
            out.append(R("hags", cat, "Hardware-accelerated GPU scheduling", "good", "On.", weight=4))
        else:
            out.append(R("hags", cat, "Hardware-accelerated GPU scheduling", "warn", "Off.",
                         "Needed for DLSS Frame Generation on RTX 40/50 and can lower latency.",
                         weight=4, fix="tweak:hags", fix_label="Turn on (needs restart)"))
    # ---------- windowed optimisations
    t = tweaks.BY_ID["windowed_opt"]
    if tweaks.safe_applied(t):
        out.append(R("winopt", cat, "Optimizations for windowed games", "good", "On.", weight=3))
    else:
        out.append(R("winopt", cat, "Optimizations for windowed games", "warn", "Off.",
                     "Turning this on gives borderless games lower latency and lets G-Sync/FreeSync work.",
                     weight=3, fix="tweak:windowed_opt", fix_label="Turn on"))
    # ---------- NVIDIA extras
    nv = info.get("nvidia")
    if nv:
        try:
            wc, wm = int(nv["pcie.link.width.current"]), int(nv["pcie.link.width.max"])
            if wc < wm:
                out.append(R("pcie", cat, "PCIe slot speed", "bad",
                             f"Graphics card is running at x{wc} lanes instead of x{wm}.",
                             "The GPU is probably in the wrong slot (use the top long slot, closest to the CPU), "
                             "not fully seated, or on a bad riser cable. An NVMe drive in certain M.2 slots can "
                             "also steal lanes - check your motherboard manual.", weight=10))
            else:
                out.append(R("pcie", cat, "PCIe slot speed", "good", f"Full x{wc} lanes.", weight=10))
        except (KeyError, ValueError):
            pass
        try:
            temp = int(nv["temperature.gpu"])
            st = "good" if temp < 80 else "warn"
            out.append(R("gputemp", cat, "GPU temperature (now)", st, f"{temp}°C right now.",
                         "Over 83°C under load means it's time to clean dust, improve airflow or set a fan curve."
                         if st == "warn" else "Check it again while gaming - under 80°C under load is healthy.",
                         weight=3 if st == "warn" else 0))
        except (KeyError, ValueError):
            pass
    out.append(R("gpupanel", cat, "GPU control panel settings", "info",
                 "Things only you can set in the NVIDIA App / AMD Software:",
                 "- Turn on G-Sync / FreeSync (if your monitor supports it).\n"
                 "- In games: turn on NVIDIA Reflex (On + Boost) or AMD Anti-Lag.\n"
                 "- Use DLSS / FSR 'Quality' instead of lowering resolution.\n"
                 "- Cap FPS 3 below your refresh rate when using G-Sync (e.g. 277 on 280Hz) for smoothest feel.",
                 weight=0))
    return out


# =================================================================== STORAGE
def check_storage(info):
    cat = "Storage"
    out = []
    vols = info.get("volumes", [])
    for v in vols:
        size = float(v.get("Size") or 0)
        free = float(v.get("SizeRemaining") or 0)
        if size < 20 * 1024 ** 3:
            continue
        pct = free / size * 100
        letter = v.get("Letter")
        title = f"Drive {letter}: free space"
        if pct < 8:
            out.append(R(f"free{letter}", cat, title, "bad", f"Only {free/1024**3:.0f} GB free ({pct:.0f}%).",
                         "Nearly full drives get slow, and Windows/games can't update. Free up space.",
                         weight=6, fix="page:cleanup", fix_label="Open Cleanup"))
        elif pct < 15:
            out.append(R(f"free{letter}", cat, title, "warn", f"{free/1024**3:.0f} GB free ({pct:.0f}%).",
                         "SSDs slow down when very full. Keep at least 15% free.", weight=4,
                         fix="page:cleanup", fix_label="Open Cleanup"))
        else:
            out.append(R(f"free{letter}", cat, title, "good", f"{free/1024**3:.0f} GB free ({pct:.0f}%).", weight=4))
    sysd = "C"
    media = sysinfo.drive_media(info, sysd)
    if media == "HDD":
        out.append(R("sysssd", cat, "Windows drive type", "bad", "Windows is on a hard drive (HDD)!",
                     "This is the single biggest upgrade for how fast your PC feels. Get an NVMe SSD and move "
                     "Windows to it.", weight=10))
    elif media == "SSD":
        out.append(R("sysssd", cat, "Windows drive type", "good", "Windows is on an SSD.", weight=10))
    # games on HDD
    gl = games.all_games()
    on_hdd = [g for g in gl if sysinfo.drive_media(info, g["drive"]) == "HDD"]
    if gl:
        if on_hdd:
            names = ", ".join(g["name"] for g in on_hdd[:8]) + ("..." if len(on_hdd) > 8 else "")
            out.append(R("gameshdd", cat, "Games on a hard drive", "warn",
                         f"{len(on_hdd)} game(s) installed on an HDD: {names}",
                         "Games on HDDs load slowly and can stutter while streaming textures. Move the ones you "
                         "play most to your SSD (Steam: Settings > Storage > select game > Move).", weight=6))
        else:
            out.append(R("gameshdd", cat, "Games on SSD", "good", f"All {len(gl)} detected games are on SSDs.", weight=6))
    # TRIM
    code, txt, _ = run(["fsutil", "behavior", "query", "DisableDeleteNotify"]) if IS_WINDOWS else (-1, "", "")
    m = re.search(r"NTFS\s+DisableDeleteNotify\s*=\s*(\d)", txt or "")
    if m:
        if m.group(1) == "0":
            out.append(R("trim", cat, "SSD TRIM", "good", "Enabled - keeps your SSD fast.", weight=3))
        else:
            out.append(R("trim", cat, "SSD TRIM", "bad", "TRIM is disabled!",
                         "Without TRIM your SSD gets slower over time. Fix: open Command Prompt as admin and run: "
                         "fsutil behavior set DisableDeleteNotify 0", weight=3))
    return out


# =================================================================== WINDOWS
def check_windows(info):
    cat = "Windows Gaming Settings"
    out = []
    gm = reg_get("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled")
    if gm == 0:
        out.append(R("gamemode", cat, "Game Mode", "warn", "Off.",
                     "Game Mode stops Windows Update from installing in the background and gives games priority.",
                     weight=4, fix="tweak:game_mode", fix_label="Turn on"))
    else:
        out.append(R("gamemode", cat, "Game Mode", "good", "On.", weight=4))
    dvr = reg_get("HKCU", r"System\GameConfigStore", "GameDVR_Enabled")
    hist = reg_get("HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "HistoricalCaptureEnabled")
    if dvr == 1 or hist == 1:
        out.append(R("gamedvr", cat, "Xbox Game Bar recording", "warn",
                     "Game DVR / background recording is on." if hist == 1 else "Game DVR capture is on.",
                     "Recording in the background costs FPS. Use NVIDIA/AMD's own recorder instead.",
                     weight=5, fix="tweak:game_dvr", fix_label="Turn off"))
    else:
        out.append(R("gamedvr", cat, "Xbox Game Bar recording", "good", "Off.", weight=5))
    # Memory integrity (honest: security trade-off)
    hvci = reg_get("HKLM", r"SYSTEM\CurrentControlSet\Control\DeviceGuard\Scenarios\HypervisorEnforcedCodeIntegrity", "Enabled")
    if hvci == 1:
        out.append(R("hvci", cat, "Memory Integrity (Core Isolation)", "info",
                     "On. This is a security feature - your choice.",
                     "Turning it off can give a few % more FPS in some games, but it protects you against "
                     "malicious drivers and some cheats/malware. RigTune won't turn it off for you. If you "
                     "decide to: Windows Security > Device security > Core isolation > Memory integrity.",
                     weight=0, fix="open:windowsdefender://coreisolation", fix_label="Open Core isolation"))
    # pending reboot
    if reg_key_exists("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired") or \
            reg_key_exists("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending"):
        out.append(R("reboot", cat, "Pending restart", "warn", "Windows Update is waiting for a restart.",
                     "Updates sitting half-installed can slow things down. Restart when you can.", weight=3))
    # startup apps
    try:
        n = startup.enabled_count()
        if n > 15:
            out.append(R("startup", cat, "Startup apps", "bad", f"{n} apps start with Windows.",
                         "That's a lot running in the background all the time. Turn off the ones you don't need.",
                         weight=5, fix="page:startup", fix_label="Manage startup apps"))
        elif n > 8:
            out.append(R("startup", cat, "Startup apps", "warn", f"{n} apps start with Windows.",
                         "Check if you really need all of them.", weight=5, fix="page:startup", fix_label="Manage startup apps"))
        elif IS_WINDOWS:
            out.append(R("startup", cat, "Startup apps", "good", f"{n} startup apps - clean.", weight=5))
    except Exception:  # noqa: BLE001
        pass
    # background bloat running now
    bloat = []
    from .boost import BLOAT
    for p in psutil.process_iter(["name"]):
        nm = (p.info.get("name") or "").lower()
        if any(b in nm for b in BLOAT):
            bloat.append(p.info["name"])
    bloat = sorted(set(bloat))
    if len(bloat) >= 3:
        out.append(R("bloat", cat, "Background apps running", "warn",
                     f"{len(bloat)} apps that are often heavy: {', '.join(bloat[:10])}",
                     "Close them before gaming with one click in Game Boost (and bring them back after).",
                     weight=4, fix="page:boost", fix_label="Open Game Boost"))
    elif IS_WINDOWS:
        out.append(R("bloat", cat, "Background apps running", "good",
                     "No big background hogs detected." if not bloat else f"Only {', '.join(bloat)}.", weight=4))
    return out


# =================================================================== POWER / CPU
def check_power(info):
    cat = "Power & CPU"
    out = []
    guid, name = tweaks.active_power_plan()
    laptop = sysinfo.is_laptop(info)
    cpu = info.get("cpu", {}).get("Name", "")
    dual_ccd_x3d = "X3D" in cpu and any(x in cpu for x in ("7950", "7900", "9950", "9900"))
    if guid is None:
        out.append(skip("power", cat, "Power plan"))
    elif guid == tweaks.POWER_SAVER:
        out.append(R("power", cat, "Power plan", "bad", "Power saver is active!",
                     "Your CPU is being held back on purpose. Switch to Balanced or High Performance.",
                     weight=8, fix="tweak:power_high", fix_label="Use High Performance"))
    elif dual_ccd_x3d:
        st = "good" if guid == tweaks.BALANCED else "warn"
        out.append(R("power", cat, "Power plan", st, f"{name}.",
                     f"Your {cpu} needs the BALANCED plan (with AMD chipset driver + Xbox Game Bar installed) "
                     "so games get parked onto the 3D V-Cache cores. High Performance can actually LOWER FPS on "
                     "this CPU.", weight=6))
    elif laptop:
        out.append(R("power", cat, "Power plan", "info", f"{name}.",
                     "On a laptop: plug in the charger while gaming and use 'Best performance' in "
                     "Settings > System > Power.", weight=0, fix="open:ms-settings:powersleep", fix_label="Open Power settings"))
    elif guid in (tweaks.HIGH_PERF, tweaks.ULTIMATE) or (name and ("high" in name.lower() or "ultimate" in name.lower())):
        out.append(R("power", cat, "Power plan", "good", f"{name}.", weight=6))
    else:
        out.append(R("power", cat, "Power plan", "warn", f"{name}.",
                     "High Performance keeps your CPU clocks up and reduces small stutters. On a desktop the extra "
                     "power use is tiny.", weight=6, fix="tweak:power_high", fix_label="Use High Performance"))
    # BIOS age
    bios = info.get("bios", {})
    age = _days_since(bios.get("ReleaseDate"))
    board = info.get("board", {})
    g = bios_guides.guide(board.get("Manufacturer"), board.get("Product"), sysinfo.cpu_vendor(info), "DDR5")
    if age is not None:
        if age > 730:
            out.append(R("biosage", cat, "BIOS version", "warn",
                         f"BIOS {bios.get('SMBIOSBIOSVersion', '?')} is {age // 365} years old.",
                         "BIOS updates fix RAM compatibility, stability and sometimes performance (and security). "
                         "Download the latest from your motherboard's support page and follow their guide. Don't "
                         "turn off the PC while it's flashing.", weight=3,
                         links=[l for l in g["links"] if "support" in l[0].lower()] or g["links"][:1]))
        else:
            out.append(R("biosage", cat, "BIOS version", "good",
                         f"{bios.get('SMBIOSBIOSVersion', '?')} ({bios.get('ReleaseDate')}).", weight=3))
    # CPU load at idle
    load = psutil.cpu_percent(interval=1.0)
    if load > 30:
        out.append(R("cpuload", cat, "CPU usage at idle", "warn", f"{load:.0f}% CPU used while doing nothing.",
                     "Something in the background is busy. Check Task Manager or use Game Boost.",
                     weight=4, fix="page:boost", fix_label="Open Game Boost"))
    else:
        out.append(R("cpuload", cat, "CPU usage at idle", "good", f"{load:.0f}%.", weight=4))
    return out


# =================================================================== NETWORK
def check_network(info):
    cat = "Network"
    n = info.get("net")
    if not n:
        return [skip("net", cat, "Network connection")]
    out = []
    wifi = "802.11" in (n.get("Media") or "") or re.search(r"wi-?fi|wireless|wlan", n.get("Desc", ""), re.I)
    if wifi:
        out.append(R("wifi", cat, "Connection type", "warn", f"You're on Wi-Fi ({n.get('Desc')}).",
                     "Wi-Fi adds ping spikes and packet loss. For online games, an Ethernet cable is the best "
                     "upgrade you can make. If you can't run a cable, powerline adapters or a mesh with "
                     "wired backhaul are the next best thing.", weight=5, fix="page:network", fix_label="Test my ping"))
    else:
        out.append(R("wifi", cat, "Connection type", "good", f"Ethernet ({n.get('Desc')}).", weight=5))
        sp = (n.get("Speed") or "").lower()
        if "100 mbps" in sp or "10 mbps" in sp:
            out.append(R("linkspeed", cat, "Ethernet link speed", "warn", f"Link is only {n.get('Speed')}.",
                         "Your port supports more. Usually a damaged/old cable (Cat5) or a bad port. Try a Cat6 cable.",
                         weight=3))
    return out


# =================================================================== RUNNER
ALL_CHECKS = [
    ("Display", check_displays),
    ("Mouse", check_mouse),
    ("RAM / XMP", check_ram),
    ("Graphics card", check_gpu),
    ("Storage & games", check_storage),
    ("Windows settings", check_windows),
    ("Power & BIOS", check_power),
    ("Network", check_network),
]


def run_all(progress=None):
    def p(frac, text):
        if progress:
            progress(frac, text)

    p(0.02, "Reading your hardware...")
    info = sysinfo.collect(force=True)
    results = []
    for i, (label, fn) in enumerate(ALL_CHECKS):
        p(0.15 + 0.8 * i / len(ALL_CHECKS), f"Checking {label}...")
        try:
            results.extend(fn(info))
        except Exception as e:  # noqa: BLE001
            results.append(R(f"err_{label}", label, f"{label} check", "skip", f"Check crashed: {e}", weight=0))
    p(1.0, "Done")
    return info, results


def score(results):
    total = sum(r.weight for r in results if r.status in ("good", "warn", "bad"))
    lost = sum(r.weight * (1.0 if r.status == "bad" else 0.5) for r in results if r.status in ("warn", "bad"))
    if total == 0:
        return 0
    return max(0, round(100 * (1 - lost / total)))


def grade(s):
    if s >= 92:
        return "Fully tuned", "#22c55e"
    if s >= 80:
        return "Good", "#84cc16"
    if s >= 65:
        return "Needs work", "#f59e0b"
    return "Leaving FPS on the table", "#ef4444"


def ordered(results):
    rank = {"bad": 0, "warn": 1, "info": 2, "good": 3, "skip": 4}
    return sorted(results, key=lambda r: (rank[r.status], -r.weight))


def now_str():
    return time.strftime("%Y-%m-%d %H:%M")
