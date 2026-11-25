"""Collect hardware / OS info in one PowerShell call (plus nvidia-smi)."""
import os
import re
import shutil

from .win import IS_WINDOWS, as_list, ps_json, run

_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
function D($d){ if($d){ try { return ([datetime]$d).ToString('yyyy-MM-dd') } catch { return $null } } return $null }
$o = [ordered]@{}
$o.cpu   = Get-CimInstance Win32_Processor | Select-Object -First 1 Name, Manufacturer, NumberOfCores, NumberOfLogicalProcessors, MaxClockSpeed
$o.board = Get-CimInstance Win32_BaseBoard | Select-Object -First 1 Manufacturer, Product
$o.bios  = Get-CimInstance Win32_BIOS | Select-Object -First 1 Manufacturer, SMBIOSBIOSVersion, @{n='ReleaseDate';e={ D $_.ReleaseDate }}
$o.ram   = @(Get-CimInstance Win32_PhysicalMemory | Select-Object Manufacturer, PartNumber, Capacity, Speed, ConfiguredClockSpeed, SMBIOSMemoryType, DeviceLocator, BankLabel)
$o.gpu   = @(Get-CimInstance Win32_VideoController | Select-Object Name, AdapterCompatibility, DriverVersion, @{n='DriverDate';e={ D $_.DriverDate }}, PNPDeviceID)
$o.os    = Get-CimInstance Win32_OperatingSystem | Select-Object -First 1 Caption, Version, BuildNumber
$o.cs    = Get-CimInstance Win32_ComputerSystem | Select-Object -First 1 Manufacturer, Model, PCSystemType, TotalPhysicalMemory
$o.battery = @(Get-CimInstance Win32_Battery).Count
$o.disks = @(Get-Partition | Where-Object { $_.DriveLetter } | ForEach-Object {
    $p = $_
    $d = Get-PhysicalDisk | Where-Object { [string]$_.DeviceId -eq [string]$p.DiskNumber } | Select-Object -First 1
    [pscustomobject]@{ Letter=[string]$p.DriveLetter; DiskNumber=$p.DiskNumber; MediaType=[string]$d.MediaType; BusType=[string]$d.BusType; Model=[string]$d.FriendlyName }
})
$o.volumes = @(Get-Volume | Where-Object { $_.DriveLetter } | Select-Object @{n='Letter';e={[string]$_.DriveLetter}}, Size, SizeRemaining, FileSystemLabel)
$r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1
if($r){ $a = Get-NetAdapter -InterfaceIndex $r.InterfaceIndex
  if($a){ $o.net = [pscustomobject]@{ Name=$a.Name; Desc=$a.InterfaceDescription; Media=[string]$a.PhysicalMediaType; Speed=[string]$a.LinkSpeed } } }
ConvertTo-Json -InputObject $o -Depth 5 -Compress
"""

_cache = None


def _nvidia_smi():
    exe = shutil.which("nvidia-smi")
    if not exe and IS_WINDOWS:
        cand = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "nvidia-smi.exe")
        exe = cand if os.path.exists(cand) else None
    if not exe:
        return None
    fields = ["name", "driver_version", "temperature.gpu", "utilization.gpu",
              "pcie.link.gen.current", "pcie.link.gen.max",
              "pcie.link.width.current", "pcie.link.width.max",
              "memory.total", "power.draw"]
    code, out, _ = run([exe, "--query-gpu=" + ",".join(fields),
                        "--format=csv,noheader,nounits"], timeout=15)
    if code != 0 or not out.strip():
        return None
    parts = [p.strip() for p in out.strip().splitlines()[0].split(",")]
    return dict(zip(fields, parts))


def collect(force=False):
    global _cache
    if _cache is not None and not force:
        return _cache
    info = ps_json(_PS, timeout=90) or {}
    for k in ("ram", "gpu", "disks", "volumes"):
        info[k] = as_list(info.get(k))
    for k in ("cpu", "board", "bios", "os", "cs"):
        v = info.get(k)
        if isinstance(v, list):
            info[k] = v[0] if v else {}
        info[k] = info.get(k) or {}
    info["nvidia"] = _nvidia_smi()
    _cache = info
    return info


# ------------------------------------------------------------- helpers
DISCRETE_RE = re.compile(r"(GeForce|RTX|GTX|Quadro|Radeon\s+(RX|Pro|VII)|Arc\s+[AB]\d)", re.I)


def is_discrete(name):
    return bool(name and DISCRETE_RE.search(name))


def cpu_vendor(info):
    n = (info.get("cpu", {}).get("Name") or "") + (info.get("cpu", {}).get("Manufacturer") or "")
    if "AMD" in n.upper():
        return "AMD"
    if "INTEL" in n.upper():
        return "Intel"
    return "Unknown"


def is_laptop(info):
    return (info.get("battery") or 0) > 0 or info.get("cs", {}).get("PCSystemType") == 2


def nvidia_version(driver_version):
    """WMI '32.0.15.6094' -> NVIDIA '560.94'."""
    if not driver_version:
        return None
    digits = "".join(driver_version.split(".")[-2:])
    if len(digits) >= 5:
        d = digits[-5:]
        return f"{d[:3]}.{d[3:]}"
    return driver_version


def drive_media(info, letter):
    """Return 'SSD', 'HDD' or 'Unknown' for a drive letter."""
    letter = (letter or "").rstrip(":\\").upper()
    for d in info.get("disks", []):
        if (d.get("Letter") or "").upper() == letter:
            mt = (d.get("MediaType") or "").upper()
            bus = (d.get("BusType") or "").upper()
            if mt == "SSD" or bus == "NVME":
                return "SSD"
            if mt == "HDD":
                return "HDD"
    return "Unknown"


def summary_lines(info):
    c = info.get("cpu", {})
    b = info.get("board", {})
    lines = [
        f"OS:          {info.get('os', {}).get('Caption', '?')} (build {info.get('os', {}).get('BuildNumber', '?')})",
        f"CPU:         {c.get('Name', '?')} - {c.get('NumberOfCores', '?')} cores / {c.get('NumberOfLogicalProcessors', '?')} threads",
        f"Motherboard: {b.get('Manufacturer', '?')} {b.get('Product', '')}",
        f"BIOS:        {info.get('bios', {}).get('SMBIOSBIOSVersion', '?')} ({info.get('bios', {}).get('ReleaseDate', '?')})",
    ]
    total = sum(int(r.get("Capacity") or 0) for r in info.get("ram", []))
    lines.append(f"RAM:         {total / 1024**3:.0f} GB in {len(info.get('ram', []))} stick(s)")
    for r in info.get("ram", []):
        lines.append(f"   - {r.get('DeviceLocator', '?')}: {int(r.get('Capacity') or 0)/1024**3:.0f} GB "
                     f"{r.get('Manufacturer', '')} {(r.get('PartNumber') or '').strip()} "
                     f"@ {r.get('ConfiguredClockSpeed', '?')} MT/s (rated {r.get('Speed', '?')})")
    for g in info.get("gpu", []):
        lines.append(f"GPU:         {g.get('Name', '?')} - driver {g.get('DriverVersion', '?')} ({g.get('DriverDate', '?')})")
    nv = info.get("nvidia")
    if nv:
        lines.append(f"   NVIDIA:   driver {nv.get('driver_version')}, {nv.get('temperature.gpu')}°C, "
                     f"PCIe Gen{nv.get('pcie.link.gen.current')} x{nv.get('pcie.link.width.current')} "
                     f"(max Gen{nv.get('pcie.link.gen.max')} x{nv.get('pcie.link.width.max')})")
    for v in info.get("volumes", []):
        size = float(v.get("Size") or 0)
        free = float(v.get("SizeRemaining") or 0)
        if size:
            lines.append(f"Drive {v.get('Letter')}:    {free/1024**3:.0f} GB free of {size/1024**3:.0f} GB "
                         f"[{drive_media(info, v.get('Letter'))}] {v.get('FileSystemLabel') or ''}")
    n = info.get("net")
    if n:
        lines.append(f"Network:     {n.get('Name')} - {n.get('Desc')} ({n.get('Speed')})")
    return lines
