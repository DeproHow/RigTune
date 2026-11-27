"""Fresh Start: 'reset my PC' without losing games, files or apps.

Repairs Windows with its own tools (DISM, SFC), resets the bits that commonly break
(Windows Update, Store, icon cache, network), turns back on services that
'optimizer' tools disabled, and removes bloatware. A restore point is made first.
"""
import os

from . import cleanup
from .win import IS_WINDOWS, as_list, is_admin, ps, ps_json, run


def _clean(s):
    return (s or "").replace("\x00", "").strip()


# ---------------------------------------------------------------- repair steps
def _dism():
    code, out, err = run(["DISM.exe", "/Online", "/Cleanup-Image", "/RestoreHealth"], timeout=3600)
    out = _clean(out)
    if code == 0:
        return True, "Windows image is healthy (repaired anything that was broken)"
    if "0x800f081f" in out.lower() or "source files could not be found" in out.lower():
        return False, "DISM couldn't download repair files - check your internet and try again"
    return False, f"DISM failed (code {code})"


def _sfc():
    code, out, err = run(["sfc.exe", "/scannow"], timeout=3600)
    t = _clean(out).lower().replace("\r", " ").replace("\n", " ")
    if "did not find any integrity violations" in t:
        return True, "No broken system files found"
    if "successfully repaired" in t:
        return True, "Found broken system files and repaired them ✔ (restart to finish)"
    if "unable to fix" in t:
        return False, ("Found broken files it couldn't fix. Run Fresh Start once more after a restart - "
                       "if it still fails, a Windows reinstall (keep files) is the next step.")
    if "pending" in t:
        return False, "A repair is waiting for a restart. Restart, then run this again."
    return code == 0, "System file check done" if code == 0 else f"SFC failed (code {code})"


def _component_cleanup():
    code, _o, _e = run(["DISM.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"], timeout=3600)
    return (True, "Old update leftovers removed") if code == 0 else (False, f"Failed (code {code})")


WU_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$svc = 'wuauserv','bits','cryptsvc','msiserver','UsoSvc'
foreach ($s in $svc) { Stop-Service -Name $s -Force }
Start-Sleep -Seconds 2
$sd = "$env:SystemRoot\SoftwareDistribution"; $cr = "$env:SystemRoot\System32\catroot2"
Remove-Item "$sd.rigtune-old" -Recurse -Force; Remove-Item "$cr.rigtune-old" -Recurse -Force
Rename-Item $sd "SoftwareDistribution.rigtune-old" -Force
Rename-Item $cr "catroot2.rigtune-old" -Force
foreach ($s in $svc) { Start-Service -Name $s }
if (Test-Path "$sd.rigtune-old") { 'OK' } else { 'PARTIAL' }
"""


def _wu_reset():
    out = _clean(ps(WU_SCRIPT, timeout=180))
    if out.endswith("OK"):
        return True, "Windows Update reset (it'll re-check for updates next time)"
    return True, "Windows Update services restarted (some files were in use - restart and try again if updates still fail)"


def _store_reset():
    code, _o, _e = run(["wsreset.exe"], timeout=180)
    run(["taskkill", "/im", "WinStore.App.exe", "/f"])
    return True, "Microsoft Store cache cleared"


ICON_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
Stop-Process -Name explorer -Force
Start-Sleep -Seconds 2
Remove-Item "$env:LOCALAPPDATA\IconCache.db" -Force
Remove-Item "$env:LOCALAPPDATA\Microsoft\Windows\Explorer\iconcache_*.db" -Force
Start-Sleep -Seconds 1
if (-not (Get-Process explorer -ErrorAction SilentlyContinue)) { Start-Process explorer.exe }
'OK'
"""


def _icon_cache():
    ps(ICON_SCRIPT, timeout=60)
    return True, "Icon cache rebuilt (taskbar flickered - that's normal)"


def _search_rebuild():
    out = _clean(ps(r"""$ErrorActionPreference='Stop'; try {
Set-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows Search' -Name SetupCompletedSuccessfully -Value 0 -Type DWord
Restart-Service WSearch -Force; 'OK' } catch { 'ERR ' + $_ }""", timeout=120))
    if out.startswith("OK"):
        return True, "Search index is rebuilding in the background (can take an hour+, search is limited till then)"
    return False, "Couldn't rebuild search: " + out


def _dns_flush():
    code, _o, _e = run(["ipconfig", "/flushdns"])
    return (True, "DNS cache flushed") if code == 0 else (False, "Failed")


def _network_reset():
    msgs = []
    for cmd in (["netsh", "winsock", "reset"], ["netsh", "int", "ip", "reset"], ["ipconfig", "/flushdns"]):
        code, _o, _e = run(cmd, timeout=60)
        msgs.append(code == 0)
    if all(msgs):
        return True, "Network stack reset (restart needed)"
    return False, "Part of the network reset failed"


def _chkdsk():
    code, out, _e = run(["chkdsk", os.environ.get("SystemDrive", "C:"), "/scan"], timeout=1800)
    t = _clean(out).lower()
    if "no problems" in t or "found no problems" in t:
        return True, "Drive checked - no problems"
    if code == 0:
        return True, "Drive checked"
    return False, "Problems found on the drive - Windows will offer to fix them on next restart"


def _junk():
    freed = 0
    for t in cleanup.scan():
        if t["default"]:
            freed += cleanup.clean(t)
    return True, f"Cleaned {cleanup.human(freed)} of temp files and crash dumps"


STEPS = [
    # id, name, description, func, admin, minutes, restart, default
    ("dism", "Repair the Windows image (DISM)",
     "Downloads clean copies of broken Windows components from Microsoft. Needs internet.",
     _dism, True, "5-20 min", False, True),
    ("sfc", "Fix broken system files (SFC)",
     "Checks every Windows system file and replaces corrupted ones. Runs after DISM on purpose.",
     _sfc, True, "5-15 min", False, True),
    ("components", "Remove old update leftovers",
     "Deletes superseded Windows Update files in WinSxS. Often frees a few GB. You can't uninstall old "
     "updates after this.", _component_cleanup, True, "2-10 min", False, True),
    ("junk", "Clean temp files & crash dumps",
     "Same as the Cleanup tab's safe defaults.", _junk, False, "<1 min", False, True),
    ("wu", "Reset Windows Update",
     "Fixes updates that are stuck, failing or downloading forever.", _wu_reset, True, "1 min", False, True),
    ("store", "Reset the Microsoft Store",
     "Fixes Store / Game Pass apps that won't download or open. The Store may pop up - just close it.",
     _store_reset, False, "<1 min", False, True),
    ("icons", "Rebuild the icon cache",
     "Fixes blank or wrong icons. Your taskbar will disappear for a second.", _icon_cache, False, "<1 min",
     False, True),
    ("dns", "Flush the DNS cache",
     "Fixes 'site can't be reached' for one specific site. Harmless.", _dns_flush, False, "<1 min", False, True),
    ("network", "Full network reset",
     "Resets Winsock and TCP/IP. For internet that's broken or weird ping. If you set a static IP or "
     "use a VPN adapter, you'll need to set those up again.", _network_reset, True, "<1 min", True, False),
    ("search", "Rebuild Windows Search",
     "For a Start menu search that's slow or doesn't find things. Rebuilds in the background for a while.",
     _search_rebuild, True, "1 min + background", False, False),
    ("chkdsk", "Check the drive for errors",
     "Read-only scan of your C: drive. Doesn't change anything by itself.", _chkdsk, True, "1-5 min",
     False, False),
]

STEP_BY_ID = {s[0]: s for s in STEPS}


def run_step(sid):
    s = STEP_BY_ID[sid]
    if not IS_WINDOWS:
        return False, "Windows only"
    if s[4] and not is_admin():
        return False, "Needs admin"
    try:
        return s[3]()
    except Exception as e:  # noqa: BLE001
        return False, f"Error: {e}"


# ---------------------------------------------------------------- services
# name: (friendly name, windows default start type, why it matters, ticked by default)
SERVICES = {
    "wuauserv": ("Windows Update", "demand", "No security updates or driver updates without it.", True),
    "UsoSvc": ("Update Orchestrator", "delayed-auto", "Needed for Windows Update to work.", True),
    "BITS": ("Background Intelligent Transfer", "demand", "Windows Update and the Store download with it.", True),
    "WSearch": ("Windows Search", "delayed-auto", "Start menu / File Explorer search.", True),
    "Spooler": ("Print Spooler", "auto", "Printing. Only needed if you print.", False),
    "Themes": ("Themes", "auto", "Windows visuals. Disabling it makes Windows look broken.", True),
    "AudioSrv": ("Windows Audio", "auto", "No sound without it.", True),
    "AudioEndpointBuilder": ("Audio Endpoint Builder", "auto", "No sound without it.", True),
    "WlanSvc": ("Wi-Fi (WLAN AutoConfig)", "auto", "Wi-Fi won't work without it.", True),
    "Dhcp": ("DHCP Client", "auto", "Gets you an IP address - internet breaks without it.", True),
    "BthServ": ("Bluetooth Support", "demand", "Bluetooth headsets, controllers and mice.", True),
    "XblAuthManager": ("Xbox Live Auth Manager", "demand", "Signing in to Game Pass / Xbox games.", True),
    "XblGameSave": ("Xbox Live Game Save", "demand", "Cloud saves for Game Pass / Xbox games.", True),
    "XboxNetApiSvc": ("Xbox Live Networking", "demand", "Multiplayer in Xbox / Game Pass games.", True),
    "XboxGipSvc": ("Xbox Accessory Management", "demand", "Xbox controllers.", True),
    "SysMain": ("SysMain (Superfetch)", "auto", "Preloads apps you use a lot. Harmless on SSDs, "
                "some people turn it off on purpose.", False),
    "W32Time": ("Windows Time", "demand", "Keeps your clock right (wrong clock breaks some games/logins).", True),
}

SC_NAMES = {"auto": "Automatic", "delayed-auto": "Automatic (delayed)", "demand": "Manual"}


def disabled_services():
    if not IS_WINDOWS:
        return []
    names = ",".join(f"'{n}'" for n in SERVICES)
    data = ps_json(f"Get-Service -Name {names} -ErrorAction SilentlyContinue | "
                   "Select-Object Name, @{n='Start';e={[string]$_.StartType}} | ConvertTo-Json -Compress")
    out = []
    for d in as_list(data):
        name = d.get("Name")
        if name in SERVICES and d.get("Start") == "Disabled":
            fn, start, why, default = SERVICES[name]
            out.append({"name": name, "friendly": fn, "start": start, "why": why, "default": default})
    return out


def restore_service(name):
    start = SERVICES[name][1]
    code, out, err = run(["sc.exe", "config", name, "start=", start])
    if code != 0:
        return False, f"{SERVICES[name][0]}: couldn't change it ({_clean(out) or _clean(err)})"
    if start != "demand":
        run(["sc.exe", "start", name])
    return True, f"{SERVICES[name][0]} set back to {SC_NAMES[start]}"


# ---------------------------------------------------------------- bloatware
# (match, friendly name, ticked by default, note). match = exact package name or prefix ending with '*'
BLOAT = [
    ("king.com.*", "Candy Crush & other King games", True, ""),
    ("Microsoft.BingNews", "Microsoft News", True, ""),
    ("Microsoft.BingWeather", "Weather", True, ""),
    ("Microsoft.BingSearch", "Bing Search", True, ""),
    ("Microsoft.GetHelp", "Get Help", True, ""),
    ("Microsoft.Getstarted", "Tips", True, ""),
    ("Microsoft.MicrosoftSolitaireCollection", "Solitaire Collection", True, ""),
    ("Microsoft.MicrosoftOfficeHub", "Office / Microsoft 365 ad app", True, "Doesn't remove real Office."),
    ("Microsoft.People", "People", True, ""),
    ("Microsoft.WindowsFeedbackHub", "Feedback Hub", True, ""),
    ("Microsoft.WindowsMaps", "Maps", True, ""),
    ("Microsoft.ZuneVideo", "Movies & TV", True, ""),
    ("Microsoft.549981C3F5F10", "Cortana", True, ""),
    ("Clipchamp.Clipchamp", "Clipchamp", True, ""),
    ("Microsoft.Todos", "Microsoft To Do", True, ""),
    ("Microsoft.PowerAutomateDesktop", "Power Automate", True, ""),
    ("Microsoft.MixedReality.Portal", "Mixed Reality Portal", True, ""),
    ("Microsoft.Microsoft3DViewer", "3D Viewer", True, ""),
    ("Microsoft.SkypeApp", "Skype", True, ""),
    ("MicrosoftTeams", "Teams (personal chat)", True, "Work/school Teams is a different app."),
    ("Microsoft.WindowsCommunicationsApps", "Mail & Calendar (old)", False, ""),
    ("*TikTok*", "TikTok", True, ""),
    ("*Facebook*", "Facebook", True, ""),
    ("*Instagram*", "Instagram", True, ""),
    ("*Disney*", "Disney+", False, ""),
    ("AmazonVideo.PrimeVideo", "Prime Video", False, ""),
    ("SpotifyAB.SpotifyMusic", "Spotify", False, "Only if you don't use it."),
    ("Microsoft.YourPhone", "Phone Link", False, "Keep if you connect your phone to your PC."),
    ("Microsoft.OutlookForWindows", "New Outlook", False, ""),
    ("Microsoft.GamingApp", "Xbox app", False, "Keep if you play Game Pass games!"),
    ("Microsoft.XboxGamingOverlay", "Xbox Game Bar", False, "Win+G overlay. Keep if you use it for clips or chat."),
]


def _match(pat, name):
    pl, nl = pat.lower(), name.lower()
    if pl.startswith("*") and pl.endswith("*"):
        return pl.strip("*") in nl
    if pl.endswith("*"):
        return nl.startswith(pl[:-1])
    return pl == nl


def installed_bloat():
    if not IS_WINDOWS:
        return []
    data = ps_json("Get-AppxPackage | Select-Object Name, PackageFullName | ConvertTo-Json -Compress", timeout=90)
    out, seen = [], set()
    for d in as_list(data):
        n = d.get("Name") or ""
        for pat, friendly, default, note in BLOAT:
            if _match(pat, n) and n not in seen:
                seen.add(n)
                out.append({"name": n, "full": d.get("PackageFullName"), "friendly": friendly,
                            "default": default, "note": note})
                break
    return sorted(out, key=lambda b: (not b["default"], b["friendly"].lower()))


def remove_app(pkg):
    full = pkg["full"].replace("'", "''")
    out = _clean(ps(f"try {{ Remove-AppxPackage -Package '{full}' -ErrorAction Stop; 'OK' }} "
                    f"catch {{ 'ERR ' + $_.Exception.Message }}", timeout=180))
    if out.startswith("OK"):
        return True, f"Removed {pkg['friendly']}"
    return False, f"{pkg['friendly']}: {out[4:120] or 'failed'}"


def restart_pc():
    run(["shutdown", "/r", "/t", "15", "/c", "RigTune Fresh Start: restarting to finish repairs"])
