"""Disk space analyzer: what's eating your storage, and what's safe to delete.

Works like TreeSize/WizTree (folder-by-folder scan, so it's slower than WizTree's
MFT trick but needs no special access). Every delete goes through `safety()` first,
and the default delete goes to the Recycle Bin so it can be undone.
"""
import ctypes
import hashlib
import heapq
import os
import shutil
import stat
import time

from . import games as games_mod
from .win import IS_WINDOWS, is_admin, run

REPARSE = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT (junctions / symlinks / OneDrive placeholders)
TOP_N = 300
OLD_DAYS = 180
OLD_MIN = 100 * 1024 ** 2   # 100 MB
DUP_MIN = 5 * 1024 ** 2     # 5 MB

CATEGORIES = {
    "games":     ("🎮 Games", "#8b5cf6"),
    "windows":   ("🪟 Windows & system", "#3b82f6"),
    "apps":      ("📦 Apps (Program Files)", "#06b6d4"),
    "appdata":   ("⚙ App data & caches", "#14b8a6"),
    "junk":      ("🧹 Temp & junk", "#22c55e"),
    "recycle":   ("🗑 Recycle Bin", "#84cc16"),
    "videos":    ("🎬 Videos", "#ef4444"),
    "images":    ("🖼 Pictures", "#f97316"),
    "music":     ("🎵 Music & audio", "#eab308"),
    "installers": ("💿 Installers & archives", "#ec4899"),
    "docs":      ("📄 Documents", "#a3a3a3"),
    "other":     ("❔ Other", "#6b7280"),
}

EXT = {}
for _cat, _exts in {
    "videos": "mp4 mkv avi mov wmv flv webm m4v ts mts",
    "images": "jpg jpeg png gif bmp webp heic raw cr2 nef psd tif tiff",
    "music": "mp3 wav flac aac ogg m4a wma",
    "installers": "zip rar 7z iso exe msi tar gz img cab",
    "docs": "pdf doc docx xls xlsx ppt pptx txt odt csv",
}.items():
    for _e in _exts.split():
        EXT["." + _e] = _cat


# ---------------------------------------------------------------- tree
class Node:
    __slots__ = ("name", "path", "size", "files", "children", "parent", "cat")

    def __init__(self, name, path, parent, cat):
        self.name = name
        self.path = path
        self.size = 0
        self.files = 0
        self.children = []
        self.parent = parent
        self.cat = cat


class ScanResult:
    def __init__(self, root):
        self.root = root
        self.index = {}          # lower path -> Node
        self.top_files = []      # heap of (size, path, mtime, last_used)
        self.old_files = []      # (size, path, last_used)
        self.dup_candidates = {}  # size -> [paths]
        self.cats = {k: 0 for k in CATEGORIES}
        self.file_count = 0
        self.dir_count = 0
        self.denied = 0
        self.system_files = {}   # pagefile.sys / hiberfil.sys / swapfile.sys -> size
        self.seconds = 0.0
        self.cancelled = False

    def biggest(self, n=150):
        return sorted(self.top_files, reverse=True)[:n]

    def node(self, path):
        return self.index.get(os.path.normcase(os.path.abspath(path)))


def _special_dirs():
    """Folders that decide the category of everything under them."""
    sp = {}

    def add(p, cat):
        if p:
            sp[os.path.normcase(os.path.abspath(p))] = cat

    if IS_WINDOWS:
        win = os.environ.get("SystemRoot", r"C:\Windows")
        add(win, "windows")
        add(os.path.join(win, "Temp"), "junk")
        add(os.path.join(win, "SoftwareDistribution", "Download"), "junk")
        for v in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            add(os.environ.get(v), "apps")
        add(os.environ.get("ProgramData"), "appdata")
        la = os.environ.get("LOCALAPPDATA")
        add(os.environ.get("APPDATA"), "appdata")
        add(la, "appdata")
        if la:
            add(os.path.join(os.path.dirname(la), "LocalLow"), "appdata")
            add(os.path.join(la, "Temp"), "junk")
            add(os.path.join(la, "CrashDumps"), "junk")
        add(os.environ.get("TEMP"), "junk")
        for d in "CDEFGHIJKLMNOPQRSTUVWXYZ":
            add(f"{d}:\\$Recycle.Bin", "recycle")
            add(f"{d}:\\Windows.old", "windows")
            add(f"{d}:\\System Volume Information", "windows")
        try:
            for g in games_mod.all_games():
                add(g["path"], "games")
        except Exception:  # noqa: BLE001
            pass
        for v, cat in (("Videos", "videos"), ("Pictures", "images"), ("Music", "music")):
            add(os.path.join(os.path.expanduser("~"), v), cat)
    return sp


def _is_reparse(entry):
    try:
        st = entry.stat(follow_symlinks=False)
    except OSError:
        return True
    if getattr(st, "st_file_attributes", 0) & REPARSE:
        return True
    return stat.S_ISLNK(st.st_mode)


def scan(root, progress=None, cancel=None):
    """Scan a drive or folder. progress(files, dirs, current_path); cancel = threading.Event."""
    t0 = time.time()
    root = os.path.abspath(root)
    special = _special_dirs()
    rnode = Node(root, root, None, special.get(os.path.normcase(root), "other"))
    res = ScanResult(rnode)
    res.index[os.path.normcase(root)] = rnode
    order = [rnode]
    stack = [rnode]
    now = time.time()
    old_cut = now - OLD_DAYS * 86400
    last_cb = 0
    sysnames = {"pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log"}

    while stack:
        if cancel is not None and cancel.is_set():
            res.cancelled = True
            break
        node = stack.pop()
        try:
            it = os.scandir(node.path)
        except OSError:
            res.denied += 1
            continue
        with it:
            for e in it:
                try:
                    if e.is_dir(follow_symlinks=False):
                        if _is_reparse(e):
                            continue
                        cp = os.path.normcase(e.path)
                        child = Node(e.name, e.path, node, special.get(cp, node.cat))
                        node.children.append(child)
                        res.index[cp] = child
                        order.append(child)
                        stack.append(child)
                        res.dir_count += 1
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    res.denied += 1
                    continue
                size = st.st_size
                node.size += size
                node.files += 1
                res.file_count += 1
                name_l = e.name.lower()
                if node is rnode and name_l in sysnames:
                    res.system_files[name_l] = size
                    cat = "windows"
                elif node.cat == "other":
                    cat = EXT.get(os.path.splitext(name_l)[1], "other")
                else:
                    cat = node.cat
                res.cats[cat] += size
                last_used = max(st.st_mtime, st.st_atime)
                item = (size, e.path, st.st_mtime, last_used)
                if len(res.top_files) < TOP_N:
                    heapq.heappush(res.top_files, item)
                elif size > res.top_files[0][0]:
                    heapq.heapreplace(res.top_files, item)
                if size >= OLD_MIN and last_used < old_cut and cat not in ("windows", "apps", "games"):
                    res.old_files.append((size, e.path, last_used))
                if size >= DUP_MIN and cat not in ("windows", "apps", "games", "recycle"):
                    res.dup_candidates.setdefault(size, []).append(e.path)
                if progress and res.file_count - last_cb >= 4000:
                    last_cb = res.file_count
                    progress(res.file_count, res.dir_count, node.path)

    # sizes bottom-up: children were always added after their parent
    for n in reversed(order):
        if n.parent is not None:
            n.parent.size += n.size
            n.parent.files += n.files
    res.old_files.sort(reverse=True)
    res.seconds = time.time() - t0
    return res


def folder_files(path, limit=60):
    """Files directly inside a folder (the tree only keeps folders)."""
    out = []
    try:
        with os.scandir(path) as it:
            for e in it:
                try:
                    if e.is_file(follow_symlinks=False):
                        st = e.stat(follow_symlinks=False)
                        out.append((st.st_size, e.path, st.st_mtime))
                except OSError:
                    pass
    except OSError:
        pass
    out.sort(reverse=True)
    return out[:limit]


def folder_size(path):
    total = 0
    for r, _d, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(r, f))
            except OSError:
                pass
    return total


# ---------------------------------------------------------------- drives
def drives():
    import psutil
    out = []
    for p in psutil.disk_partitions(all=False):
        if IS_WINDOWS and ("cdrom" in p.opts or not p.fstype):
            continue
        try:
            u = psutil.disk_usage(p.mountpoint)
        except OSError:
            continue
        out.append({"path": p.mountpoint, "total": u.total, "used": u.used, "free": u.free,
                    "fstype": p.fstype})
    return out


# ---------------------------------------------------------------- safety
def _env_path(v, *parts):
    base = os.environ.get(v)
    return os.path.normcase(os.path.join(base, *parts)) if base else None


def safety(path):
    """('red'|'yellow'|'green', reason). Red = RigTune will refuse to delete it."""
    p = os.path.normcase(os.path.abspath(path))
    drive, rest = os.path.splitdrive(p)
    rest = rest.strip("\\/")
    if not rest:
        return "red", "This is a whole drive."
    first = rest.split(os.sep)[0]
    name = os.path.basename(p)
    if name in ("pagefile.sys", "hiberfil.sys", "swapfile.sys", "dumpstack.log", "bootmgr"):
        return "red", "Windows system file. Use the quick-win button instead if there is one."
    if first in ("windows", "system volume information", "$recycle.bin", "boot", "recovery",
                 "$winreagent", "$windows.~bt", "$windows.~ws", "efi"):
        if first == "windows" and p.startswith(os.path.join(drive + os.sep, "windows", "temp")):
            return "green", "Windows temp files. Safe."
        return "red", "Part of Windows. Deleting this can stop your PC from booting."
    if first == "windows.old":
        return "red", "Old Windows install. Remove it with the 'Windows.old' quick win (Disk Cleanup) instead."
    home = os.path.normcase(os.path.expanduser("~"))
    roots = {os.path.normcase(x) for x in filter(None, (
        os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramData"),
        os.environ.get("APPDATA"), os.environ.get("LOCALAPPDATA"), os.path.dirname(home), home))}
    if p in roots:
        return "red", "Core Windows folder. Delete things inside it, not the folder itself."
    for t in filter(None, (_env_path("TEMP"), _env_path("LOCALAPPDATA", "Temp"),
                           _env_path("LOCALAPPDATA", "CrashDumps"))):
        if p == t or p.startswith(t + os.sep):
            return "green", "Temp files. Safe."
    for g in _game_paths():
        if p == g or p.startswith(g + os.sep):
            return "yellow", "Part of an installed game. Uninstall it from the launcher instead, or the launcher gets confused."
    for v in ("ProgramFiles", "ProgramFiles(x86)"):
        b = _env_path(v)
        if b and p.startswith(b + os.sep):
            return "yellow", "Installed app. Uninstall it from Settings > Apps instead of deleting the folder."
    for v in ("ProgramData", "APPDATA", "LOCALAPPDATA"):
        b = _env_path(v)
        if b and p.startswith(b + os.sep):
            return "yellow", "App settings / data. Usually safe for apps you've uninstalled, but can reset an app you still use."
    if p.startswith(os.path.join(home, "documents")):
        return "yellow", "Documents - game saves and configs often live here. Check first."
    for f in ("downloads", "desktop", "videos", "pictures", "music"):
        if p.startswith(os.path.join(home, f)):
            return "green", "Your own file. Won't break Windows - just make sure you don't need it."
    if os.path.splitext(p)[1] in EXT and EXT[os.path.splitext(p)[1]] in ("videos", "installers", "music", "images"):
        return "green", "Media/installer file. Won't break Windows - just make sure you don't need it."
    return "yellow", "Not sure what this is. Check what it belongs to before deleting."


_GAME_CACHE = {"t": 0, "paths": []}


def _game_paths():
    if time.time() - _GAME_CACHE["t"] > 120:
        try:
            _GAME_CACHE["paths"] = [os.path.normcase(os.path.abspath(g["path"])) for g in games_mod.all_games()]
        except Exception:  # noqa: BLE001
            _GAME_CACHE["paths"] = []
        _GAME_CACHE["t"] = time.time()
    return _GAME_CACHE["paths"]


# ---------------------------------------------------------------- delete
if IS_WINDOWS:
    from ctypes import wintypes

    class _SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT),
                    ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                    ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]


def to_recycle_bin(path):
    if not IS_WINDOWS:
        return False, "Windows only"
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO = 3, 0x4, 0x10, 0x40
    FOF_NOERRORUI, FOF_WANTNUKEWARNING = 0x400, 0x4000
    op = _SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    op.pFrom = os.path.abspath(path) + "\0"
    op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI | FOF_WANTNUKEWARNING
    r = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if r == 0 and not op.fAnyOperationsAborted and not os.path.exists(path):
        return True, "Moved to the Recycle Bin"
    if os.path.exists(path):
        return False, "Couldn't delete it - something is using it, or it needs admin."
    return True, "Moved to the Recycle Bin"


def delete_forever(path):
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.remove(path)
    except OSError as e:
        return False, f"Couldn't delete: {e.strerror or e}"
    if os.path.exists(path):
        return False, "Some files were in use and got skipped."
    return True, "Deleted permanently"


def delete(path, permanent=False):
    level, why = safety(path)
    if level == "red":
        return False, "RigTune won't delete this: " + why
    return delete_forever(path) if permanent else to_recycle_bin(path)


def forget(res, path, size):
    """Update a scan result after something was deleted, so the UI stays right."""
    if res is None:
        return
    key = os.path.normcase(os.path.abspath(path))
    node = res.index.pop(key, None)
    if node is not None:
        for k in [k for k in res.index if k.startswith(key + os.sep)]:
            res.index.pop(k, None)
        if node.parent:
            node.parent.children = [c for c in node.parent.children if c is not node]
        parent = node.parent
        files = node.files
    else:
        parent = res.node(os.path.dirname(path))
        files = 1
    while parent is not None:
        parent.size = max(0, parent.size - size)
        parent.files = max(0, parent.files - files)
        parent = parent.parent
    res.top_files = [f for f in res.top_files if not os.path.normcase(f[1]).startswith(key)]
    heapq.heapify(res.top_files)
    res.old_files = [f for f in res.old_files if not os.path.normcase(f[1]).startswith(key)]


# ---------------------------------------------------------------- duplicates
def _hash(path, partial):
    h = hashlib.blake2b(digest_size=20)
    try:
        with open(path, "rb") as f:
            if partial:
                h.update(f.read(65536))
                try:
                    f.seek(-65536, os.SEEK_END)
                except OSError:
                    pass
                h.update(f.read(65536))
            else:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicates(res, progress=None, cancel=None):
    """Groups of identical files (same content, not just same name). Biggest waste first."""
    groups = []
    cands = [(s, p) for s, p in res.dup_candidates.items() if len(p) > 1]
    for i, (size, paths) in enumerate(sorted(cands, reverse=True)):
        if cancel is not None and cancel.is_set():
            break
        if progress:
            progress(i + 1, len(cands))
        by_partial = {}
        for p in paths:
            k = _hash(p, True)
            if k:
                by_partial.setdefault(k, []).append(p)
        for same in by_partial.values():
            if len(same) < 2:
                continue
            by_full = {}
            for p in same:
                k = _hash(p, False) if size > 131072 else _hash(p, True)
                if k:
                    by_full.setdefault(k, []).append(p)
            for dup in by_full.values():
                if len(dup) > 1:
                    groups.append({"size": size, "paths": dup, "wasted": size * (len(dup) - 1)})
    groups.sort(key=lambda g: g["wasted"], reverse=True)
    return groups


# ---------------------------------------------------------------- games
def games_with_sizes(res=None):
    out = []
    for g in games_mod.all_games():
        node = res.node(g["path"]) if res else None
        size = node.size if node else (folder_size(g["path"]) if os.path.isdir(g["path"]) else 0)
        out.append({**g, "size": size})
    out.sort(key=lambda g: g["size"], reverse=True)
    return out


# ---------------------------------------------------------------- quick wins
def recycle_bin_size():
    if not IS_WINDOWS:
        return 0, 0

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong)]
    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
        return info.i64Size, info.i64NumItems
    return 0, 0


def empty_recycle_bin():
    if not IS_WINDOWS:
        return False, "Windows only"
    r = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x2 | 0x4)
    return (True, "Recycle Bin emptied") if r in (0, -2147418113) else (False, f"Failed (code {r})")


def hibernation_off():
    if not is_admin():
        return False, "Needs admin"
    code, _o, err = run(["powercfg", "/hibernate", "off"])
    return (True, "Hibernation off - hiberfil.sys is gone") if code == 0 else (False, err.strip() or "Failed")


def quick_wins(res):
    """Big, safe space wins that don't show up as normal files to delete."""
    wins = []
    rb, items = recycle_bin_size()
    if rb > 100 * 1024 ** 2:
        wins.append({"id": "recycle", "title": "Empty the Recycle Bin", "size": rb,
                     "desc": f"{items} item(s) you already deleted are still taking space.",
                     "label": "Empty it"})
    hib = res.system_files.get("hiberfil.sys", 0) if res else 0
    if hib > 1024 ** 3:
        wins.append({"id": "hiber", "title": "Turn off hibernation (hiberfil.sys)", "size": hib,
                     "desc": "Desktop PCs almost never need hibernation. This also turns off Fast Startup, "
                             "which a lot of gamers do anyway (it causes weird driver issues).",
                     "label": "Turn off", "admin": True})
    if res:
        drive = os.path.splitdrive(res.root.path)[0]
        wo = res.node(drive + "\\Windows.old") if drive else None
        if wo and wo.size > 0:
            wins.append({"id": "winold", "title": "Remove Windows.old", "size": wo.size,
                         "desc": "Leftover copy of your previous Windows version. You can't go back to it after "
                                 "removing it, but if your PC works fine you won't need to. Opens Disk Cleanup - "
                                 "tick 'Previous Windows installation(s)'.",
                         "label": "Open Disk Cleanup"})
    return wins


def run_quick_win(wid):
    if wid == "recycle":
        return empty_recycle_bin()
    if wid == "hiber":
        return hibernation_off()
    if wid == "winold":
        run(["cleanmgr.exe", "/d", "C:"], timeout=5)
        return True, "Disk Cleanup opened - click 'Clean up system files' then tick Previous Windows installation(s)"
    return False, "Unknown"


# ---------------------------------------------------------------- helpers
def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def ago(ts):
    if not ts:
        return "unknown"
    d = (time.time() - ts) / 86400
    if d < 1:
        return "today"
    if d < 2:
        return "yesterday"
    if d < 31:
        return f"{int(d)} days ago"
    if d < 365:
        return f"{int(d // 30)} month(s) ago"
    return f"{d / 365:.1f} years ago"
