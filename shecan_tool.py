import subprocess
import time
import sys
import os
import json
import re
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError
from socket import create_connection

SHECAN_DNS = ["178.22.122.100", "185.51.200.2", "178.22.122.101", "185.51.200.1"]
SHECAN_PRIMARY = "178.22.122.101"
SHECAN_SECONDARY = "185.51.200.1"
FALLBACK_DNS = "8.8.8.8"
TEST_DOMAIN = "shecan.ir"
TEST_TIMEOUT = 5

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
SAMPLE_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config-sample.json")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

DEFAULT_CONFIG = {
    "update_urls": [],
    "interval_minutes": 5,
    "ip_check_url": "https://ip.shecan.ir/"
}


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    if os.path.exists(SAMPLE_CONFIG_FILE):
        with open(SAMPLE_CONFIG_FILE, "r") as f:
            return json.load(f)
    return dict(DEFAULT_CONFIG)


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"fallback_added": False}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_configured_dns():
    cmd = [
        "powershell", "-NoProfile", "-Command",
        "Get-DnsClientServerAddress -AddressFamily IPv4 "
        "| Where-Object { $_.ServerAddresses -and $_.InterfaceAlias -notmatch 'Loopback|Bluetooth|VMware|Virtual|Hyper-V|vEthernet' } "
        "| Select-Object -ExpandProperty ServerAddresses"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0:
            addresses = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
            if addresses:
                return addresses
    except Exception:
        pass
    try:
        result = subprocess.run(
            ["netsh", "interface", "ip", "show", "dns"],
            capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW
        )
        if result.returncode == 0:
            dns_servers = []
            for line in result.stdout.splitlines():
                m = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                if m:
                    ip = m.group(1)
                    if not ip.startswith("0.") and ip not in dns_servers:
                        dns_servers.append(ip)
            return dns_servers
    except Exception:
        pass
    return []


def is_using_shecan_dns(dns_list):
    return any(dns in SHECAN_DNS for dns in dns_list)


def get_active_interface():
    cmd = [
        "powershell", "-NoProfile", "-Command",
        "Get-NetAdapter -Physical | Where-Object Status -eq 'Up' | Select-Object -First 1 -ExpandProperty Name"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0:
            name = result.stdout.strip()
            if name:
                return name
    except Exception:
        pass

    cmd2 = [
        "powershell", "-NoProfile", "-Command",
        "Get-NetAdapter -InterfaceDescription *Wi-Fi*,*Ethernet*,*Wireless* | Where-Object Status -eq 'Up' | Select-Object -First 1 -ExpandProperty Name"
    ]
    try:
        result = subprocess.run(cmd2, capture_output=True, text=True, timeout=5, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0:
            name = result.stdout.strip()
            if name:
                return name
    except Exception:
        pass
    return None


def set_dns_servers(interface_name, servers):
    servers_str = ",".join(f'"{s}"' for s in servers)
    ps_cmd = f'Set-DnsClientServerAddress -InterfaceAlias "{interface_name}" -ServerAddresses ({servers_str})'
    cmd = ["powershell", "-NoProfile", "-Command", ps_cmd]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        return result.returncode == 0
    except Exception as e:
        print(f"  [!] Failed to set DNS: {e}")
        return False


def is_shecan_alive():
    for dns in [SHECAN_PRIMARY, SHECAN_SECONDARY]:
        try:
            create_connection((dns, 53), timeout=TEST_TIMEOUT)
            return True
        except Exception:
            continue
    return False


def call_update_url(url):
    try:
        req = Request(url, method="GET", headers={"User-Agent": "ShecanChecker/1.0"})
        resp = urlopen(req, timeout=15)
        body = resp.read().decode("utf-8", errors="replace").strip()
        return True, body[:100]
    except Exception as e:
        return False, str(e)


def check_ip_service(url):
    try:
        req = Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0"})
        resp = urlopen(req, timeout=15)
        body = resp.read().decode("utf-8", errors="replace").strip()
        return True, body[:100]
    except Exception as e:
        return False, str(e)


def log(msg):
    print(f"[{timestamp()}] {msg}")


def run_cycle(config, state, cycle_num=None):
    label = f"Cycle {cycle_num}" if cycle_num else ""
    print(f"\n{'='*60}")
    print(f"[{timestamp()}] {label}")

    dns_list = get_configured_dns()
    using_shecan = is_using_shecan_dns(dns_list)
    dns_str = ", ".join(dns_list) if dns_list else "(none)"
    print(f"  DNS configured : {dns_str}")
    print(f"  Shecan DNS     : {'YES' if using_shecan else 'NO'}")

    shecan_alive = is_shecan_alive()
    print(f"  Shecan alive   : {'YES' if shecan_alive else 'NO'}")

    iface = get_active_interface()
    fallback_added = state.get("fallback_added", False)

    if using_shecan and not shecan_alive and not fallback_added and iface:
        log(f"Shecan unreachable — adding fallback {FALLBACK_DNS} to [{iface}]")
        # Put fallback FIRST so DNS resolution doesn't wait through dead Shecan servers.
        ok = set_dns_servers(iface, [FALLBACK_DNS, SHECAN_PRIMARY, SHECAN_SECONDARY])
        if ok:
            state["fallback_added"] = True
            save_state(state)
            print(f"  DNS fallback   : ADDED {FALLBACK_DNS}")
        else:
            print(f"  DNS fallback   : FAILED")

    elif shecan_alive and fallback_added and iface:
        log(f"Shecan back online — removing fallback, restoring Shecan-only DNS on [{iface}]")
        ok = set_dns_servers(iface, [SHECAN_PRIMARY, SHECAN_SECONDARY])
        if ok:
            state["fallback_added"] = False
            save_state(state)
            print(f"  DNS fallback   : REMOVED")
        else:
            print(f"  DNS fallback   : FAILED to restore")

    elif fallback_added:
        print(f"  DNS fallback   : ACTIVE ({FALLBACK_DNS} added)")

    dns_now = get_configured_dns()
    dns_now_str = ", ".join(dns_now) if dns_now else "(none)"
    print(f"  DNS current    : {dns_now_str}")

    dns_ok = shecan_alive or FALLBACK_DNS in dns_now
    if dns_ok:
        for i, url in enumerate(config["update_urls"], 1):
            ok, msg = call_update_url(url)
            print(f"  Update {i}      : [{'OK' if ok else 'FAIL'}] {msg}")
        ip_ok, ip_msg = check_ip_service(config["ip_check_url"])
        print(f"  IP check       : [{'OK' if ip_ok else 'FAIL'}] {ip_msg}")
    else:
        print(f"  Updates        : SKIPPED (no working DNS)")


def main():
    config = load_config()
    state = load_state()
    interval = config["interval_minutes"] * 60

    print(f"Shecan DNS Tool — interval: {config['interval_minutes']} min")
    print(f"Shecan DNS     : {SHECAN_PRIMARY} / {SHECAN_SECONDARY}")
    print(f"Fallback DNS   : {FALLBACK_DNS}")
    print(f"Update URLs    : {len(config['update_urls'])} configured")
    print(f"Config file    : {CONFIG_FILE}")
    if not os.path.exists(CONFIG_FILE):
        print("  [!] config.json not found — copy config-sample.json and set your DDNS passwords.")

    if "--once" in sys.argv:
        run_cycle(config, state)
        return

    cycle = 0
    while True:
        cycle += 1
        run_cycle(config, state, cycle)
        if interval > 0:
            time.sleep(interval)


if __name__ == "__main__":
    main()
