"""
Inventory Collector (Supabase version)
----------------------------------------
Run by employees (as a compiled .exe). Asks for full name + company
email, collects basic machine info, and inserts a row directly into a
Supabase (Postgres) table via the REST API.

If the network/Supabase call fails for any reason (no internet, VPN
issue, etc.), the data is saved as a local .json backup instead, so
nothing is lost -- IT can re-upload it manually later.
"""

import sys
import os
import socket
import platform
import subprocess
import uuid
import getpass
import json
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
# From Supabase dashboard: Project Settings > API
SUPABASE_URL = "https://plfndkojwojpgvtrxjuh.supabase.co/rest/v1/"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBsZm5ka29qd29qcGd2dHJ4anVoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODMzNjc0OTUsImV4cCI6MjA5ODk0MzQ5NX0.Q_8QV2AXFM4hqS885yNSoXCSKT5l0zzjvxxMkv8v5Fo"   # anon/public key ONLY. Never the service_role key.
TABLE_NAME = "inventory_reports"

# Local fallback used ONLY if the Supabase insert fails
LOCAL_BACKUP_FOLDER = os.path.join(os.path.expanduser("~"), "InventoryBackup")
# =============================================


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


def collect_system_data():
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
    }


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
    response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
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
    sys_data = collect_system_data()

    payload = {
        "full_name": full_name,
        "email": email,
        **sys_data,
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
