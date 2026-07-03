# Shecan DNS Guardian

**A lightweight Windows watchdog for [Shecan](https://shecan.ir) DNS — monitors health, auto-failover, and DDNS updates.**

> Unofficial community tool. Not affiliated with or endorsed by Shecan.

[English](#english) · [فارسی](#فارسی)

---

## English

### Why this exists

[Shecan](https://shecan.ir) is a popular Iranian DNS service that helps users reach filtered websites. Two common pain points:

1. **Outages** — When Shecan DNS servers are unreachable, Windows may stall on every lookup and browsing breaks (`ERR_NAME_NOT_RESOLVED`).
2. **Dynamic IP** — Users with changing public IPs must notify Shecan so traffic is routed correctly.

This tool runs in the background, checks Shecan every few minutes, adds a temporary fallback DNS when needed, and pings your DDNS update URLs automatically.

### Features

- **DNS monitoring** — Reads current Windows DNS settings (PowerShell + `netsh` fallback)
- **Health checks** — TCP probe on port 53 (no circular DNS dependency)
- **Automatic failover** — Adds `8.8.8.8` when Shecan is down; removes it when Shecan recovers
- **DDNS updates** — Calls your Shecan update URLs on each healthy cycle
- **Public IP check** — Optional endpoint to verify connectivity
- **Persistent state** — Remembers failover status across restarts (`state.json`)
- **Zero dependencies** — Standard library only (Python 3.7+)
- **Single-file core** — Easy to read, fork, and customize

### Requirements

| Requirement | Notes |
|-------------|-------|
| Windows 10/11 | Uses PowerShell 5.1+ and `netsh` |
| Python 3.7+ | Must be on `PATH` |
| Administrator | Required to change DNS via `Set-DnsClientServerAddress` |
| Shecan DNS | Configure your adapter to Shecan before running (see below) |

### Quick start

```batch
git clone https://github.com/SahandM96/shecan_checker.git
cd shecan_checker

copy config-sample.json config.json
:: Edit config.json — add your DDNS update URLs from my.shecan.ir

:: Run as Administrator
python shecan_tool.py
```

**One-shot check (no loop):**

```batch
python shecan_tool.py --once
```

**Double-click launcher:**

```batch
run_checker.bat
```

### Initial DNS setup

If Shecan is not configured yet:

1. **Settings** → **Network & Internet** → **Change adapter options**
2. Right-click your active adapter → **Properties**
3. **Internet Protocol Version 4 (TCP/IPv4)** → **Properties**
4. **Use the following DNS server addresses**
5. Preferred: `178.22.122.101` · Alternate: `185.51.200.1`

### Configuration

Copy `config-sample.json` to `config.json` (never commit `config.json`).

```json
{
  "update_urls": [
    "https://ddns.shecan.ir/update?password=YOUR_PASSWORD_HERE"
  ],
  "interval_minutes": 5,
  "ip_check_url": "https://ip.shecan.ir/"
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `update_urls` | `string[]` | `[]` | DDNS update URLs from your Shecan panel |
| `interval_minutes` | `int` | `5` | Minutes between monitoring cycles |
| `ip_check_url` | `string` | `https://ip.shecan.ir/` | URL that returns your public IP |

Get DDNS URLs from [my.shecan.ir](https://my.shecan.ir/panel/). You can list multiple URLs if you have more than one service.

### How it works

```
┌─────────────┐     every N min     ┌──────────────────┐
│ Read DNS    │ ─────────────────▶│ Shecan reachable?│
└─────────────┘                   └────────┬─────────┘
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              ▼                            ▼                            ▼
         Shecan OK                   Shecan DOWN                   No Shecan DNS
         + no fallback               + no fallback                 → warn only
         → idle                     → add 8.8.8.8 first
         Shecan OK                   Shecan DOWN
         + fallback active           + fallback active
         → restore Shecan DNS        → keep fallback
              │                            │
              └────────────┬───────────────┘
                           ▼
                    DDNS + IP check (if DNS works)
```

**Failover order when Shecan is down:** `8.8.8.8` is placed **first** so Windows does not wait on dead Shecan servers.

**Default Shecan servers used by the tool:**

| Role | Address |
|------|---------|
| Primary | `178.22.122.101` |
| Secondary | `185.51.200.1` |
| Fallback | `8.8.8.8` |

### Sample output

**Normal operation:**

```
============================================================
[2026-07-02 16:10:00] Cycle 12
  DNS configured : 192.168.1.1, 178.22.122.101, 185.51.200.1
  Shecan DNS     : YES
  Shecan alive   : YES
  DNS current    : 192.168.1.1, 178.22.122.101, 185.51.200.1
  Update 1       : [OK] 203.0.113.42
  IP check       : [OK] 203.0.113.42
```

**Shecan down — fallback added:**

```
  Shecan alive   : NO
  DNS fallback   : ADDED 8.8.8.8
  DNS current    : 8.8.8.8, 178.22.122.101, 185.51.200.1
```

**Shecan recovered — fallback removed:**

```
  Shecan alive   : YES
  DNS fallback   : REMOVED
```

### Project structure

```
shecan_checker/
├── shecan_tool.py       # Main application
├── config-sample.json   # Configuration template
├── config.json          # Your config (gitignored)
├── state.json           # Runtime state (gitignored)
├── run_checker.bat      # Windows launcher
├── check_shecan.py      # Legacy script (deprecated)
└── README.md
```

### Known limitations

- **Windows only** — Uses PowerShell and `netsh`; no Linux/macOS support yet
- **Admin required** — Without elevation, failover cannot change DNS
- **Single instance** — Do not run two copies; they share `state.json`
- **Virtual adapters** — VMware/Hyper-V adapters may slow DNS reads (5s timeout + `netsh` fallback)
- **DNS cache delay** — After a full outage, Windows may need 1–2 minutes before lookups recover
- **Fallback scope** — `8.8.8.8` restores basic DNS; some filtered sites may not work until Shecan returns

### Roadmap

- [ ] System tray / background mode
- [ ] Desktop notifications on outage/recovery
- [ ] Auto-start via Task Scheduler
- [ ] File logging
- [ ] Configurable fallback DNS in `config.json`
- [ ] Linux support

### Contributing

Contributions are welcome.

1. Fork the repository
2. Create a feature branch (`git checkout -b feat/my-change`)
3. Commit with [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, …)
4. Open a Pull Request

Please do not commit `config.json`, real DDNS passwords, or personal IPs.

### License

MIT — see [LICENSE](LICENSE).

### Disclaimer

This is free software provided as-is, with no warranty. Always keep a manual DNS fallback plan. Use at your own risk.

---

## فارسی

### معرفی

**نگهبان DNS شکن** یک ابزار سبک ویندوزی برای کاربران [شکن](https://shecan.ir) است که:

- وضعیت DNS شکن را مانیتور می‌کند
- در صورت قطعی، به‌صورت خودکار DNS پشتیبان (`8.8.8.8`) اضافه می‌کند
- پس از برگشت سرویس، تنظیمات شکن را بازمی‌گرداند
- لینک‌های DDNS را برای اعلام IP جدید به‌روز می‌کند

> ابزار غیررسمی جامعه کاربری است و وابسته به تیم شکن نیست.

### ویژگی‌ها

- مانیتورینگ دوره‌ای DNS و سلامت سرورهای شکن
- Failover خودکار بدون وابستگی به DNS lookup
- پشتیبانی از چند URL به‌روزرسانی DDNS
- بدون وابستگی خارجی — فقط Python استاندارد
- مناسب اجرای دائمی در پس‌زمینه

### نصب سریع

```batch
git clone https://github.com/SahandM96/shecan_checker.git
cd shecan_checker
copy config-sample.json config.json
:: پسوردهای DDNS را از پنل my.shecan.ir در config.json قرار دهید
python shecan_tool.py
```

**اجرا حتماً با دسترسی Administrator.**

### تنظیم DNS شکن

| نقش | آدرس |
|-----|------|
| اصلی | `178.22.122.101` |
| جایگزین | `185.51.200.1` |

### کانفیگ

فایل `config-sample.json` را به `config.json` کپی کنید. پسورد DDNS را از [پنل شکن](https://my.shecan.ir/panel/) بگیرید.

**هشدار امنیتی:** `config.json` را commit نکنید — در `.gitignore` قرار دارد.

### محدودیت‌ها

- فقط ویندوز
- نیاز به Admin برای تغییر DNS
- فقط یک instance همزمان اجرا شود
- در قطعی طولانی، `8.8.8.8` اینترنت را برمی‌گرداند اما ممکن است سایت‌های فیلترشده در دسترس نباشند

### مشارکت

Fork → branch → PR. از Conventional Commits استفاده کنید.

### مجوز

MIT — استفاده، تغییر و توزیع آزاد.
