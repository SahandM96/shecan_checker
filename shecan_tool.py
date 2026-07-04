import ctypes
import subprocess
import time
import sys
import os
import json
import re
from datetime import datetime
from urllib.request import Request, urlopen
from socket import create_connection

SHECAN_DNS = ["178.22.122.100", "185.51.200.2", "178.22.122.101", "185.51.200.1"]
SHECAN_PRIMARY = "178.22.122.101"
SHECAN_SECONDARY = "185.51.200.1"
DEFAULT_FALLBACK_DNS = "8.8.8.8"
TEST_TIMEOUT = 5
DNS_READ_RETRIES = 3
DNS_READ_BACKOFF = 1

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
SAMPLE_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config-sample.json")
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")

DEFAULT_CONFIG = {
    "update_urls": [],
    "interval_minutes": 5,
    "ip_check_url": "https://ip.shecan.ir/",
    "dns_failover": "auto",
    "fallback_dns": DEFAULT_FALLBACK_DNS,
}

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
    elif os.path.exists(SAMPLE_CONFIG_FILE):
        with open(SAMPLE_CONFIG_FILE, "r") as f:
            config = json.load(f)
    else:
        config = dict(DEFAULT_CONFIG)
    for key, value in DEFAULT_CONFIG.items():
        config.setdefault(key, value)
    return config


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {"fallback_added": False}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg):
    print(f"[{timestamp()}] {msg}")


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


def run_powershell(ps_cmd, timeout=5):
    cmd = ["powershell", "-NoProfile", "-Command", ps_cmd]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        return None


def get_default_route_interface():
    ps_cmd = (
        "$r = Get-NetRoute -DestinationPrefix '0.0.0.0/0' -AddressFamily IPv4 "
        "| Sort-Object RouteMetric | Select-Object -First 1; "
        "if ($r) { (Get-NetAdapter -InterfaceIndex $r.InterfaceIndex -ErrorAction SilentlyContinue).Name }"
    )
    result = run_powershell(ps_cmd)
    if result and result.returncode == 0:
        name = result.stdout.strip()
        if name:
            return name

    ps_cmd2 = (
        "Get-NetAdapter -Physical | Where-Object Status -eq 'Up' "
        "| Select-Object -First 1 -ExpandProperty Name"
    )
    result = run_powershell(ps_cmd2)
    if result and result.returncode == 0:
        name = result.stdout.strip()
        if name:
            return name

    ps_cmd3 = (
        "Get-NetAdapter -InterfaceDescription *Wi-Fi*,*Ethernet*,*Wireless* "
        "| Where-Object Status -eq 'Up' | Select-Object -First 1 -ExpandProperty Name"
    )
    result = run_powershell(ps_cmd3)
    if result and result.returncode == 0:
        name = result.stdout.strip()
        if name:
            return name
    return None


def read_dns_for_interface(interface_name):
    ps_cmd = (
        f"Get-DnsClientServerAddress -InterfaceAlias '{interface_name}' -AddressFamily IPv4 "
        "| Select-Object -ExpandProperty ServerAddresses"
    )
    result = run_powershell(ps_cmd)
    if result and result.returncode == 0:
        addresses = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        if addresses:
            return addresses

    try:
        netsh_result = subprocess.run(
            ["netsh", "interface", "ip", "show", "dns", f'name="{interface_name}"'],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
        )
        if netsh_result.returncode == 0:
            dns_servers = []
            for line in netsh_result.stdout.splitlines():
                match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                if match:
                    ip = match.group(1)
                    if not ip.startswith("0.") and ip not in dns_servers:
                        dns_servers.append(ip)
            return dns_servers
    except Exception:
        pass
    return []


def get_active_adapter_dns(log_retries=False):
    for attempt in range(DNS_READ_RETRIES):
        iface = get_default_route_interface()
        if iface:
            dns_list = read_dns_for_interface(iface)
            if dns_list:
                return iface, dns_list
        if log_retries and attempt < DNS_READ_RETRIES - 1:
            print(f"  DNS read       : retry {attempt + 2}/{DNS_READ_RETRIES}")
            time.sleep(DNS_READ_BACKOFF)
    return None, []


def is_using_shecan_dns(dns_list):
    return any(dns in SHECAN_DNS for dns in dns_list)


def is_failover_enabled(config, using_shecan):
    mode = config.get("dns_failover", "auto")
    if mode == "disabled":
        return False
    if mode == "enabled":
        return True
    return using_shecan


def dedupe_preserve_order(servers):
    seen = set()
    result = []
    for server in servers:
        if server not in seen:
            seen.add(server)
            result.append(server)
    return result


def build_fallback_dns_list(current_servers, fallback_dns):
    others = [s for s in current_servers if s not in SHECAN_DNS and s != fallback_dns]
    shecan = [s for s in current_servers if s in SHECAN_DNS]
    if not shecan:
        shecan = [SHECAN_PRIMARY, SHECAN_SECONDARY]
    return dedupe_preserve_order([fallback_dns] + others + shecan)


def dns_set_matches(expected, actual):
    return set(expected) == set(actual)


def set_dns_servers(interface_name, servers):
    servers_str = ",".join(f'"{s}"' for s in servers)
    ps_cmd = (
        f'Set-DnsClientServerAddress -InterfaceAlias "{interface_name}" '
        f"-ServerAddresses ({servers_str})"
    )
    result = run_powershell(ps_cmd, timeout=15)
    if result is None:
        return False, "PowerShell timed out or failed to start"
    if result.returncode != 0:
        err = (result.stderr or result.stdout or "unknown error").strip()
        return False, err[:200]
    return True, ""


def flush_dns_cache():
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        pass


def apply_dns_change(iface, servers, state, label):
    before = read_dns_for_interface(iface)
    servers_str = ", ".join(servers)
    print(f"  DNS {label:<7}      : [{iface}] {before} -> {servers}")

    ok, err = set_dns_servers(iface, servers)
    if not ok:
        print(f"  DNS {label:<7}      : FAILED ({err})")
        return False

    time.sleep(0.5)
    after = read_dns_for_interface(iface)
    if not after:
        print(f"  DNS {label:<7}      : VALIDATION FAILED (empty DNS after change)")
        rollback = state.get("dns_backup", {}).get("servers")
        if rollback:
            set_dns_servers(iface, rollback)
        return False
    if not dns_set_matches(servers, after):
        print(f"  DNS {label:<7}      : VALIDATION FAILED (expected {servers}, got {after})")
        rollback = state.get("dns_backup", {}).get("servers")
        if rollback:
            set_dns_servers(iface, rollback)
        return False

    flush_dns_cache()
    print(f"  DNS {label:<7}      : OK")
    return True


def clear_stale_fallback_state(state):
    state["fallback_added"] = False
    state.pop("dns_backup", None)
    save_state(state)


def is_shecan_alive():
    for dns in [SHECAN_PRIMARY, SHECAN_SECONDARY]:
        try:
            create_connection((dns, 53), timeout=TEST_TIMEOUT)
            return True
        except Exception:
            continue
    return False


def has_working_dns(dns_list):
    if not dns_list:
        return False
    for dns in dns_list:
        try:
            create_connection((dns, 53), timeout=3)
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


def run_failover(config, state, iface, dns_list, using_shecan, shecan_alive, fallback_dns):
    fallback_added = state.get("fallback_added", False)
    can_mutate = iface and dns_list and is_admin()

    if not can_mutate:
        if fallback_added and using_shecan and shecan_alive:
            if not is_admin():
                print("  DNS fallback   : SKIPPED restore (admin required)")
            elif not dns_list:
                print("  DNS fallback   : SKIPPED restore (DNS read empty)")
            elif not iface:
                print("  DNS fallback   : SKIPPED restore (no active adapter)")
        elif using_shecan and not shecan_alive and not fallback_added:
            if not is_admin():
                print("  DNS fallback   : SKIPPED add (admin required)")
            elif not dns_list:
                print("  DNS fallback   : SKIPPED add (DNS read empty)")
            elif not iface:
                print("  DNS fallback   : SKIPPED add (no active adapter)")
        elif fallback_added:
            print(f"  DNS fallback   : ACTIVE ({fallback_dns} added)")
        return

    if using_shecan and not shecan_alive and not fallback_added:
        log(f"Shecan unreachable — adding fallback {fallback_dns} to [{iface}]")
        if "dns_backup" not in state:
            state["dns_backup"] = {"interface": iface, "servers": list(dns_list)}
        new_servers = build_fallback_dns_list(dns_list, fallback_dns)
        if apply_dns_change(iface, new_servers, state, "fallback"):
            state["fallback_added"] = True
            save_state(state)
            print(f"  DNS fallback   : ADDED {fallback_dns}")

    elif using_shecan and shecan_alive and fallback_added:
        backup = state.get("dns_backup", {})
        restore_servers = backup.get("servers") or [SHECAN_PRIMARY, SHECAN_SECONDARY]
        log(f"Shecan back online — restoring DNS on [{iface}]")
        if apply_dns_change(iface, restore_servers, state, "restore"):
            state["fallback_added"] = False
            state.pop("dns_backup", None)
            save_state(state)
            print("  DNS fallback   : REMOVED")

    elif fallback_added:
        print(f"  DNS fallback   : ACTIVE ({fallback_dns} added)")


def run_cycle(config, state, cycle_num=None):
    label = f"Cycle {cycle_num}" if cycle_num else ""
    print(f"\n{'='*60}")
    print(f"[{timestamp()}] {label}")

    fallback_dns = config.get("fallback_dns", DEFAULT_FALLBACK_DNS)
    iface, dns_list = get_active_adapter_dns(log_retries=True)
    using_shecan = is_using_shecan_dns(dns_list)
    failover_enabled = is_failover_enabled(config, using_shecan)

    if iface:
        print(f"  Adapter        : {iface}")
    dns_str = ", ".join(dns_list) if dns_list else "(none)"
    print(f"  DNS configured : {dns_str}")
    print(f"  Shecan DNS     : {'YES' if using_shecan else 'NO'}")
    print(f"  Mode           : {'failover' if failover_enabled else 'monitor_only'}")

    shecan_alive = is_shecan_alive()
    print(f"  Shecan alive   : {'YES' if shecan_alive else 'NO'}")

    if not failover_enabled:
        if state.get("fallback_added") or state.get("dns_backup"):
            clear_stale_fallback_state(state)
            print("  DNS fallback   : CLEARED (failover disabled or Shecan DNS not in use)")
    else:
        run_failover(config, state, iface, dns_list, using_shecan, shecan_alive, fallback_dns)

    _, dns_now = get_active_adapter_dns(log_retries=False)
    dns_now_str = ", ".join(dns_now) if dns_now else "(none)"
    print(f"  DNS current    : {dns_now_str}")

    if has_working_dns(dns_now):
        for i, url in enumerate(config["update_urls"], 1):
            ok, msg = call_update_url(url)
            print(f"  Update {i}      : [{'OK' if ok else 'FAIL'}] {msg}")
        ip_ok, ip_msg = check_ip_service(config["ip_check_url"])
        print(f"  IP check       : [{'OK' if ip_ok else 'FAIL'}] {ip_msg}")
    else:
        print("  Updates        : SKIPPED (no working DNS)")


def main():
    config = load_config()
    state = load_state()
    interval = config["interval_minutes"] * 60
    fallback_dns = config.get("fallback_dns", DEFAULT_FALLBACK_DNS)

    print(f"Shecan DNS Tool — interval: {config['interval_minutes']} min")
    print(f"Shecan DNS     : {SHECAN_PRIMARY} / {SHECAN_SECONDARY}")
    print(f"Fallback DNS   : {fallback_dns}")
    print(f"DNS failover   : {config.get('dns_failover', 'auto')}")
    print(f"Update URLs    : {len(config['update_urls'])} configured")
    print(f"Config file    : {CONFIG_FILE}")
    if not is_admin():
        print("  [!] Not running as Administrator — DNS failover will be skipped.")
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
