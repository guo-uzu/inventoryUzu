"""
Inventory Collector (Supabase version, v2)
--------------------------------------------
Adds: disk type per drive (SSD/HDD/NVMe), multi-disk support, RAM slot
usage + whether more RAM can be added, GPU(s) present, screen size,
laptop manufacturer/model, and session/user domain info.

The extended hardware detection uses PowerShell/WMI and only works on
Windows (which is fine, since that's what this tool targets). On other
OSes those fields are sent as null/"Unknown" so the script still runs.
"""

import sys
import os
import socket
import platform
import subprocess
import tempfile
import uuid
import getpass
import json
import math
from datetime import datetime, timezone

try:
    import psutil
except ImportError:
    print("Missing dependency: psutil. Install with: pip install psutil")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Missing dependency: requests. Install with: pip install requests")
    sys.exit(1)

import tkinter as tk
from tkinter import messagebox, simpledialog

# ================== CONFIG ==================
SUPABASE_URL = "https://plfndkojwojpgvtrxjuh.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_KPM70Y02JfOI34b8s9Ugsw_ERhkxBNF"
TABLE_NAME = "inventory_reports"

LOCAL_BACKUP_FOLDER = os.path.join(os.path.expanduser("~"), "InventoryBackup")
# =============================================


# ---------- basic info (cross-platform) ----------

def get_mac_address():
    mac_num = uuid.getnode()
    return ':'.join('{:02x}'.format((mac_num >> ele) & 0xff) for ele in range(40, -1, -8))


def get_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "Unknown"


def get_serial_number():
    system = platform.system()
    try:
        if system == "Windows":
            try:
                output = subprocess.check_output(
                    'powershell -NoProfile -Command "(Get-CimInstance Win32_BIOS).SerialNumber"',
                    shell=True, stderr=subprocess.DEVNULL
                ).decode(errors="ignore").strip()
                if output:
                    return output
            except Exception:
                pass
            try:
                output = subprocess.check_output(
                    "wmic bios get serialnumber", shell=True, stderr=subprocess.DEVNULL
                ).decode(errors="ignore")
                lines = [l.strip() for l in output.splitlines() if l.strip()]
                return lines[1] if len(lines) > 1 else "Unknown"
            except Exception:
                return "Unknown"
        elif system == "Linux":
            output = subprocess.check_output(
                "cat /sys/class/dmi/id/product_serial 2>/dev/null || echo Unknown",
                shell=True, stderr=subprocess.DEVNULL
            ).decode(errors="ignore").strip()
            return output or "Unknown"
        elif system == "Darwin":
            output = subprocess.check_output(
                "ioreg -l | grep IOPlatformSerialNumber", shell=True, stderr=subprocess.DEVNULL
            ).decode(errors="ignore")
            return output.split('"')[-2] if '"' in output else "Unknown"
    except Exception:
        return "Unknown"
    return "Unknown"


def collect_basic_data():
    disk = psutil.disk_usage(os.path.abspath(os.sep))
    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
    disk_total_gb = round(disk.total / (1024 ** 3), 2)
    disk_free_gb = round(disk.free / (1024 ** 3), 2)

    return {
        "computer_name": socket.gethostname(),
        "logged_in_user": getpass.getuser(),
        "os": f"{platform.system()} {platform.release()}",
        "os_version": platform.version(),
        "cpu": platform.processor() or "Unknown",
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_gb": ram_gb,
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb,
        "serial_number": get_serial_number(),
        "ip_address": get_ip_address(),
        "mac_address": get_mac_address(),
        "session_name": os.environ.get("SESSIONNAME", "Unknown"),
        "user_domain": os.environ.get("USERDOMAIN", "Unknown"),
    }


# ---------- extended hardware info (Windows only) ----------

POWERSHELL_SCRIPT = r"""
$ErrorActionPreference = "SilentlyContinue"

$cs   = Get-CimInstance Win32_ComputerSystem
$memArray   = Get-CimInstance Win32_PhysicalMemoryArray | Select-Object -First 1
$memModules = Get-CimInstance Win32_PhysicalMemory
$gpus       = Get-CimInstance Win32_VideoController
$physDisks  = Get-PhysicalDisk
$monitors   = Get-CimInstance -Namespace root\wmi -ClassName WmiMonitorBasicDisplayParams

$diskInfo = @()
foreach ($d in $physDisks) {
    $diskInfo += [PSCustomObject]@{
        Name      = $d.FriendlyName
        MediaType = [string]$d.MediaType
        BusType   = [string]$d.BusType
        SizeGB    = if ($d.Size) { [math]::Round($d.Size / 1GB, 2) } else { $null }
    }
}

$gpuInfo = @()
foreach ($g in $gpus) {
    $gpuInfo += [PSCustomObject]@{
        Name          = $g.Name
        AdapterRAMGB  = if ($g.AdapterRAM) { [math]::Round($g.AdapterRAM / 1GB, 2) } else { $null }
        DriverVersion = $g.DriverVersion
    }
}

$ramModuleInfo = @()
foreach ($m in $memModules) {
    $ramModuleInfo += [PSCustomObject]@{
        CapacityGB   = if ($m.Capacity) { [math]::Round($m.Capacity / 1GB, 2) } else { $null }
        SpeedMHz     = $m.Speed
        Manufacturer = $m.Manufacturer
    }
}

$screenInfo = @()
foreach ($mon in $monitors) {
    $w = [double]$mon.MaxHorizontalImageSize
    $h = [double]$mon.MaxVerticalImageSize
    if ($w -gt 0 -and $h -gt 0) {
        $diag = [math]::Round( ([math]::Sqrt(($w*$w) + ($h*$h))) / 2.54, 1)
    } else {
        $diag = $null
    }
    $screenInfo += [PSCustomObject]@{ DiagonalInches = $diag }
}

$result = [PSCustomObject]@{
    Manufacturer     = $cs.Manufacturer
    Model            = $cs.Model
    SystemFamily     = $cs.SystemFamily
    RAMSlotsTotal    = $memArray.MemoryDevices
    RAMSlotsUsed     = $ramModuleInfo.Count
    RAMMaxCapacityGB = if ($memArray.MaxCapacity) { [math]::Round($memArray.MaxCapacity / 1MB, 2) } else { $null }
    RAMModules       = $ramModuleInfo
    Disks            = $diskInfo
    GPUs             = $gpuInfo
    Screens          = $screenInfo
}

$result | ConvertTo-Json -Depth 6 -Compress
"""


def _as_list(value):
    """PowerShell's ConvertTo-Json collapses single-item arrays into a
    plain object instead of a list -- normalize that here."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def get_extended_hardware_info():
    defaults = {
        "manufacturer": "Unknown",
        "model": "Unknown",
        "system_family": "Unknown",
        "ram_slots_total": None,
        "ram_slots_used": None,
        "ram_max_capacity_gb": None,
        "ram_upgradeable": None,
        "ram_modules": [],
        "disks": [],
        "disk_count": 0,
        "has_ssd": None,
        "primary_disk_type": "Unknown",
        "gpus": [],
        "gpu_count": 0,
        "has_dedicated_gpu": None,
        "screens": [],
        "screen_size_inches": None,
    }

    if platform.system() != "Windows":
        return defaults

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".ps1", delete=False,
                                          encoding="utf-8") as tmp:
            tmp.write(POWERSHELL_SCRIPT)
            tmp_path = tmp.name

        output = subprocess.check_output(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", tmp_path],
            stderr=subprocess.DEVNULL, timeout=30
        ).decode(errors="ignore").strip()

        data = json.loads(output)

        ram_modules = _as_list(data.get("RAMModules"))
        disks = _as_list(data.get("Disks"))
        gpus = _as_list(data.get("GPUs"))
        screens = _as_list(data.get("Screens"))

        ram_slots_total = data.get("RAMSlotsTotal")
        ram_slots_used = data.get("RAMSlotsUsed") or len(ram_modules)
        ram_max_gb = data.get("RAMMaxCapacityGB")
        total_ram_installed = sum(m.get("CapacityGB") or 0 for m in ram_modules)

        ram_upgradeable = None
        if ram_slots_total is not None and ram_max_gb is not None:
            has_free_slot = ram_slots_used < ram_slots_total
            below_max = total_ram_installed < ram_max_gb
            ram_upgradeable = bool(has_free_slot or below_max)

        has_ssd = None
        primary_disk_type = "Unknown"
        if disks:
            media_types = [d.get("MediaType", "") for d in disks]
            has_ssd = any(mt == "SSD" for mt in media_types)
            primary_disk_type = disks[0].get("BusType") or disks[0].get("MediaType") or "Unknown"
            # Prefer bus type when it's informative (NVMe/SATA/etc), else media type (SSD/HDD)
            if disks[0].get("BusType") in ("NVMe",):
                primary_disk_type = "NVMe SSD"
            elif disks[0].get("MediaType") in ("SSD", "HDD"):
                primary_disk_type = disks[0]["MediaType"]

        dedicated_markers = ("nvidia", "geforce", "quadro", "rtx", "radeon rx", "radeon pro")
        integrated_markers = ("intel", "radeon graphics", "basic render", "basic display")
        has_dedicated_gpu = None
        if gpus:
            has_dedicated_gpu = False
            for g in gpus:
                name = (g.get("Name") or "").lower()
                if any(marker in name for marker in dedicated_markers):
                    has_dedicated_gpu = True
                    break

        screen_size = None
        for s in screens:
            if s.get("DiagonalInches"):
                screen_size = s["DiagonalInches"]
                break

        return {
            "manufacturer": data.get("Manufacturer") or "Unknown",
            "model": data.get("Model") or "Unknown",
            "system_family": data.get("SystemFamily") or "Unknown",
            "ram_slots_total": ram_slots_total,
            "ram_slots_used": ram_slots_used,
            "ram_max_capacity_gb": ram_max_gb,
            "ram_upgradeable": ram_upgradeable,
            "ram_modules": ram_modules,
            "disks": disks,
            "disk_count": len(disks),
            "has_ssd": has_ssd,
            "primary_disk_type": primary_disk_type,
            "gpus": gpus,
            "gpu_count": len(gpus),
            "has_dedicated_gpu": has_dedicated_gpu,
            "screens": screens,
            "screen_size_inches": screen_size,
        }
    except Exception:
        return defaults
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass


# ---------- person info / supabase / backup ----------

def ask_person_info():
    root = tk.Tk()
    root.withdraw()

    full_name = simpledialog.askstring("Inventory - Identification", "Full name:")
    if not full_name:
        messagebox.showerror("Cancelled", "Full name is required. Closing.")
        sys.exit(1)

    email = simpledialog.askstring("Inventory - Identification", "Company email:")
    if not email or "@" not in email:
        messagebox.showerror("Cancelled", "A valid email is required. Closing.")
        sys.exit(1)

    root.destroy()
    return full_name.strip(), email.strip()


def send_to_supabase(payload):
    url = f"{SUPABASE_URL}/rest/v1/{TABLE_NAME}"
    headers = {
        "apikey": SUPABASE_ANON_KEY,
        "Authorization": f"Bearer {SUPABASE_ANON_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
    if response.status_code not in (200, 201):
        raise RuntimeError(f"Supabase returned {response.status_code}: {response.text}")


def save_local_backup(payload):
    os.makedirs(LOCAL_BACKUP_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(LOCAL_BACKUP_FOLDER, f"backup_{timestamp}.json")
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    return filepath


def main():
    full_name, email = ask_person_info()
    basic = collect_basic_data()
    extended = get_extended_hardware_info()

    payload = {
        "full_name": full_name,
        "email": email,
        **basic,
        **extended,
        "collected_at": datetime.now(timezone.utc).isoformat(),
    }

    root = tk.Tk()
    root.withdraw()
    try:
        send_to_supabase(payload)
        messagebox.showinfo("Inventory", "Thank you! Your data was saved successfully.")
    except Exception as e:
        try:
            backup_path = save_local_backup(payload)
            messagebox.showwarning(
                "Saved locally instead",
                "Could not reach the server, so your data was saved locally:\n\n"
                f"{backup_path}\n\nPlease let IT know so it can be uploaded manually.\n\n"
                f"Details: {e}"
            )
        except Exception as e2:
            messagebox.showerror("Error", f"Could not save the data anywhere.\n\n{e}\n{e2}")
            sys.exit(1)
    finally:
        root.destroy()


if __name__ == "__main__":
    main()
