import subprocess
import re
import time
import sys
import json
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import URLError

SHECAN_DNS = ["178.22.122.100", "185.51.200.2"]
CHECK_URL = "https://my.shecan.ir/panel/"
INTERVAL_SECONDS = 300  # 5 minutes


def get_configured_dns():
    """Read DNS server addresses from all active network adapters via PowerShell."""
    cmd = [
        "powershell", "-Command",
        "Get-DnsClientServerAddress -AddressFamily IPv4 "
        "| Where-Object { $_.ServerAddresses -and $_.InterfaceAlias -notmatch 'Loopback|Bluetooth|VMware|Virtual|Hyper-V|vEthernet' } "
        "| Select-Object -ExpandProperty ServerAddresses"
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            addresses = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
            return addresses
    except Exception as e:
        print(f"[{timestamp()}] Error reading DNS config: {e}")
    return []


def is_using_shecan_dns(dns_list):
    """Check if any of the configured DNS servers match Shecan's."""
    return any(dns in SHECAN_DNS for dns in dns_list)


def check_panel_reachable():
    """Try to reach the Shecan panel. Returns True if reachable, False otherwise."""
    req = Request(CHECK_URL, method="GET", headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    try:
        resp = urlopen(req, timeout=15)
        return resp.status == 200
    except URLError as e:
        return False
    except Exception as e:
        return False


def timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def check_once():
    dns_list = get_configured_dns()
    using_shecan = is_using_shecan_dns(dns_list)
    panel_reachable = check_panel_reachable()

    status = "OK" if using_shecan else "WARNING"
    dns_str = ", ".join(dns_list) if dns_list else "(none)"
    print(f"[{timestamp()}] [{status}] DNS: {dns_str} | Panel reachable: {panel_reachable}")

    return {
        "timestamp": timestamp(),
        "status": status,
        "configured_dns": dns_list,
        "using_shecan": using_shecan,
        "panel_reachable": panel_reachable,
    }


def main():
    print(f"Shecan DNS Checker — interval: {INTERVAL_SECONDS}s")
    print(f"Shecan DNS servers: {', '.join(SHECAN_DNS)}")
    print("Press Ctrl+C to stop.\n")

    if "--once" in sys.argv:
        result = check_once()
        sys.exit(0 if result["using_shecan"] else 1)

    while True:
        check_once()
        time.sleep(INTERVAL_SECONDS)


if __name__ == "__main__":
    main()
