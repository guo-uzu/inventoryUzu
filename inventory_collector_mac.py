"""
Inventory Collector (Supabase version) -- macOS
--------------------------------------------------
Same data schema as the Windows version, so both write into the same
Supabase table. Uses `system_profiler` and `diskutil` (both built into
macOS, no extra tools needed) instead of PowerShell/WMI.

Note: Apple Silicon Macs (M1/M2/M3/M4) have soldered RAM -- ram_upgradeable
will correctly report False for those. Only older Intel Macs with actual
DIMM slots (iMacs, some Mac minis) can report True.
"""

import sys
import os
import socket
import platform
import subprocess
import plistlib
import uuid
import getpass
import json
from datetime import datetime, timezone

try:
    import psutil
except ImportError:
    print("Missing dependency: psutil. Install with: pip3 install psutil")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Missing dependency: requests. Install with: pip3 install requests")
    sys.exit(1)

import tkinter as tk
from tkinter import messagebox, simpledialog

# ================== CONFIG ==================
SUPABASE_URL = "https://plfndkojwojpgvtrxjuh.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_KPM70Y02JfOI34b8s9Ugsw_ERhkxBNF"
TABLE_NAME = "inventory_reports"

LOCAL_BACKUP_FOLDER = os.path.join(os.path.expanduser("~"), "InventoryBackup")
# =============================================

# Best-effort screen size lookup by Mac "Model Identifier".
# Not exhaustive -- add entries as needed. Falls back to "Unknown".
SCREEN_SIZE_BY_MODEL_ID = {
    "MacBookAir10,1": 13.3,   # MacBook Air M1
    "Mac14,2": 13.6,          # MacBook Air M2 13"
    "Mac14,15": 15.3,         # MacBook Air M2 15"
    "Mac15,12": 13.6,         # MacBook Air M3 13"
    "Mac15,13": 15.3,         # MacBook Air M3 15"
    "MacBookPro17,1": 13.3,   # MacBook Pro M1 13"
    "MacBookPro18,3": 14.2,   # MacBook Pro M1 Pro/Max 14"
    "MacBookPro18,4": 14.2,
    "MacBookPro18,1": 16.2,   # MacBook Pro M1 Pro/Max 16"
    "MacBookPro18,2": 16.2,
    "Mac14,7": 13.3,          # MacBook Pro M2 13"
    "Mac14,9": 14.2,          # MacBook Pro M2 Pro/Max 14"
    "Mac14,10": 16.2,         # MacBook Pro M2 Pro/Max 16"
    "Mac15,3": 14.2,          # MacBook Pro M3 14"
    "Mac15,6": 14.2,
    "Mac15,7": 16.2,
    "Mac15,8": 14.2,
    "Mac15,9": 16.2,
    "Mac15,10": 14.2,
    "Mac15,11": 16.2,
}


# ---------- shared helpers ----------

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


def run_system_profiler(data_type):
    """Runs `system_profiler <DataType> -json` and returns the parsed dict."""
    try:
        output = subprocess.check_output(
            ["system_profiler", data_type, "-json"],
            stderr=subprocess.DEVNULL, timeout=20
        )
        return json.loads(output)
    except Exception:
        return {}


def find_first_key_containing(obj, substr):
    """Recursively search a nested dict/list for the first key containing
    `substr` (case-insensitive) and return its value."""
    substr = substr.lower()
    if isinstance(obj, dict):
        for k, v in obj.items():
            if substr in k.lower():
                return v
        for v in obj.values():
            found = find_first_key_containing(v, substr)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_first_key_containing(item, substr)
            if found is not None:
                return found
    return None


# ---------- basic info ----------

def collect_basic_data():
    disk = psutil.disk_usage("/")
    ram_gb = round(psutil.virtual_memory().total / (1024 ** 3), 2)
    disk_total_gb = round(disk.total / (1024 ** 3), 2)
    disk_free_gb = round(disk.free / (1024 ** 3), 2)

    mac_ver = platform.mac_ver()[0] or "Unknown"

    try:
        computer_name = subprocess.check_output(
            ["scutil", "--get", "ComputerName"], stderr=subprocess.DEVNULL
        ).decode(errors="ignore").strip()
    except Exception:
        computer_name = socket.gethostname()

    hw = run_system_profiler("SPHardwareDataType")
    hw_item = (hw.get("SPHardwareDataType") or [{}])[0]
    cpu_name = hw_item.get("chip_type") or hw_item.get("cpu_type") or platform.processor() or "Unknown"
    serial = hw_item.get("serial_number") or "Unknown"

    return {
        "computer_name": computer_name,
        "logged_in_user": getpass.getuser(),
        "os": "macOS",
        "os_version": mac_ver,
        "cpu": cpu_name,
        "cpu_cores": psutil.cpu_count(logical=True),
        "ram_gb": ram_gb,
        "disk_total_gb": disk_total_gb,
        "disk_free_gb": disk_free_gb,
        "serial_number": serial,
        "ip_address": get_ip_address(),
        "mac_address": get_mac_address(),
        "session_name": "N/A (macOS)",
        "user_domain": "N/A (macOS)",
    }


# ---------- extended hardware info ----------

def get_disks_info():
    disks = []
    try:
        list_output = subprocess.check_output(
            ["diskutil", "list", "-plist"], stderr=subprocess.DEVNULL, timeout=15
        )
        list_plist = plistlib.loads(list_output)
        whole_disks = list_plist.get("WholeDisks", [])

        for disk_id in whole_disks:
            try:
                info_output = subprocess.check_output(
                    ["diskutil", "info", "-plist", disk_id],
                    stderr=subprocess.DEVNULL, timeout=15
                )
                info = plistlib.loads(info_output)
                size_bytes = info.get("TotalSize") or info.get("Size") or 0
                is_ssd = info.get("SolidState")
                bus = info.get("BusProtocol", "Unknown")
                media_type = "SSD" if is_ssd else ("HDD" if is_ssd is False else "Unknown")
                disks.append({
                    "Name": info.get("MediaName", disk_id),
                    "MediaType": media_type,
                    "BusType": bus,
                    "SizeGB": round(size_bytes / (1024 ** 3), 2) if size_bytes else None,
                })
            except Exception:
                continue
    except Exception:
        pass
    return disks


def get_gpus_info():
    gpus = []
    disp = run_system_profiler("SPDisplaysDataType")
    for entry in disp.get("SPDisplaysDataType", []):
        name = entry.get("sppci_model") or entry.get("_name") or "Unknown"
        vram_str = entry.get("sppci_vram") or entry.get("spdisplays_vram")
        vram_gb = None
        if vram_str:
            try:
                num = float(str(vram_str).split()[0])
                unit = str(vram_str).split()[-1].upper()
                vram_gb = round(num / 1024, 2) if "MB" in unit else round(num, 2)
            except Exception:
                vram_gb = None
        gpus.append({
            "Name": name,
            "AdapterRAMGB": vram_gb,
            "DriverVersion": "N/A (macOS)",
        })
    return gpus, disp


def get_screen_size(model_identifier, displays_data):
    if model_identifier in SCREEN_SIZE_BY_MODEL_ID:
        return SCREEN_SIZE_BY_MODEL_ID[model_identifier]
    return None


def get_ram_info():
    mem = run_system_profiler("SPMemoryDataType")
    mem_items = mem.get("SPMemoryDataType", [])

    ram_modules = []
    slots_total = 0
    slots_used = 0

    for item in mem_items:
        # Apple Silicon: single summary entry, no per-slot DIMM breakdown
        if "dimm_size" in item or "_name" in item and "BANK" in str(item.get("_name", "")):
            slots_total += 1
            size_str = item.get("dimm_size", "Empty")
            if size_str and size_str != "Empty":
                slots_used += 1
                ram_modules.append({
                    "CapacityGB": size_str,
                    "SpeedMHz": item.get("dimm_speed"),
                    "Manufacturer": item.get("dimm_manufacturer", "Unknown"),
                })

    is_upgradeable_raw = find_first_key_containing(mem, "upgrad")
    if isinstance(is_upgradeable_raw, str):
        ram_upgradeable = is_upgradeable_raw.strip().lower() in ("yes", "true")
    elif isinstance(is_upgradeable_raw, bool):
        ram_upgradeable = is_upgradeable_raw
    else:
        # No DIMM slot info found at all -> almost certainly Apple Silicon (soldered)
        ram_upgradeable = False if not ram_modules else None

    return {
        "ram_slots_total": slots_total or None,
        "ram_slots_used": slots_used or None,
        "ram_max_capacity_gb": None,  # macOS rarely exposes motherboard max capacity
        "ram_upgradeable": ram_upgradeable,
        "ram_modules": ram_modules,
    }


def get_extended_hardware_info():
    hw = run_system_profiler("SPHardwareDataType")
    hw_item = (hw.get("SPHardwareDataType") or [{}])[0]
    model_name = hw_item.get("machine_name", "Unknown")
    model_identifier = hw_item.get("machine_model", "Unknown")

    disks = get_disks_info()
    gpus, displays_data = get_gpus_info()
    ram_info = get_ram_info()
    screen_size = get_screen_size(model_identifier, displays_data)

    has_ssd = any(d.get("MediaType") == "SSD" for d in disks) if disks else None
    primary_disk_type = "Unknown"
    if disks:
        d0 = disks[0]
        if d0.get("BusType") in ("PCI-Express", "Apple Fabric"):
            primary_disk_type = "NVMe SSD"
        elif d0.get("MediaType") in ("SSD", "HDD"):
            primary_disk_type = d0["MediaType"]

    dedicated_markers = ("radeon pro", "radeon rx", "geforce", "nvidia", "quadro")
    has_dedicated_gpu = None
    if gpus:
        has_dedicated_gpu = any(
            any(marker in (g.get("Name") or "").lower() for marker in dedicated_markers)
            for g in gpus
        )
        # Apple Silicon integrated GPU is part of the chip -- not "dedicated"
        if all("apple m" in (g.get("Name") or "").lower() for g in gpus):
            has_dedicated_gpu = False

    return {
        "manufacturer": "Apple",
        "model": model_name,
        "system_family": model_identifier,
        "disks": disks,
        "disk_count": len(disks),
        "has_ssd": has_ssd,
        "primary_disk_type": primary_disk_type,
        "gpus": gpus,
        "gpu_count": len(gpus),
        "has_dedicated_gpu": has_dedicated_gpu,
        "screens": [{"DiagonalInches": screen_size}] if screen_size else [],
        "screen_size_inches": screen_size,
        **ram_info,
    }


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
