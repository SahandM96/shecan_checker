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
- **Automatic failover** — Adds fallback DNS when Shecan is down; restores your original DNS when Shecan recovers (only when Shecan DNS is configured)
- **Monitor-only mode** — If Shecan DNS is not on the active adapter, runs DDNS/IP checks without touching DNS settings
- **DDNS updates** — Calls your Shecan update URLs on each healthy cycle
- **Public IP check** — Optional endpoint to verify connectivity
- **Sanction mirror env vars** — Probes real domains (e.g. `pub.dev`, `storage.googleapis.com`); sets Flutter/Dart mirror URLs when blocked, removes them when all probes succeed
- **Persistent state** — Remembers failover and mirror env status across restarts (`state.json`)
- **Zero dependencies** — Standard library only (Python 3.7+)
- **Single-file core** — Easy to read, fork, and customize

### Requirements

| Requirement | Notes |
|-------------|-------|
| Windows 10/11 | Uses PowerShell 5.1+ and `netsh` |
| Python 3.7+ | Must be on `PATH` |
| Administrator | Required for DNS failover and Machine-level env vars (User env works without Admin) |
| Shecan DNS | Optional — failover activates automatically when Shecan DNS is detected |

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
  "ip_check_url": "https://ip.shecan.ir/",
  "dns_failover": "auto",
  "fallback_dns": "8.8.8.8",
  "sanction_mirrors": {
    "enabled": "auto",
    "probe_urls": [
      "https://pub.dev/api/packages/cli_util",
      "https://storage.googleapis.com/flutter_infra_release/releases/releases_windows.json"
    ],
    "env_vars": {
      "FLUTTER_STORAGE_BASE_URL": "https://flutter.devneeds.ir",
      "PUB_HOSTED_URL": "https://dart.devneeds.ir"
    },
    "env_scope": "auto"
  }
}
```

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `update_urls` | `string[]` | `[]` | DDNS update URLs from your Shecan panel |
| `interval_minutes` | `int` | `5` | Minutes between monitoring cycles |
| `ip_check_url` | `string` | `https://ip.shecan.ir/` | URL that returns your public IP |
| `dns_failover` | `string` | `"auto"` | `"auto"` = failover only when Shecan DNS detected; `"enabled"` = always allow failover; `"disabled"` = never change DNS |
| `fallback_dns` | `string` | `"8.8.8.8"` | DNS server prepended during Shecan outages |
| `sanction_mirrors.enabled` | `string` | `"auto"` | `"auto"`/`"enabled"` = probe every cycle; `"disabled"` = never change env vars |
| `sanction_mirrors.probe_urls` | `string[]` | pub.dev API + Flutter release metadata | Real URLs — **all** must respond before mirrors are removed |
| `sanction_mirrors.env_vars` | `object` | Flutter/Dart mirrors | Env var name → mirror URL applied when probes fail |
| `sanction_mirrors.env_scope` | `string` | `"auto"` | `"auto"` = User always + Machine if Admin; `"user"` / `"machine"` |

Get DDNS URLs from [my.shecan.ir](https://my.shecan.ir/panel/). You can list multiple URLs if you have more than one service.

### Sanction mirror env vars (Flutter / Dart)

When developing with Flutter in Iran, Google-hosted domains (`pub.dev`, `storage.googleapis.com`) may be blocked even when Shecan DNS is not directly configured on the active adapter (for example, when a router/local DNS proxy is used). Instead of manually setting mirror URLs in every terminal session:

```powershell
$env:FLUTTER_STORAGE_BASE_URL = "https://flutter.devneeds.ir"
$env:PUB_HOSTED_URL = "https://dart.devneeds.ir"
```

The tool probes real Flutter/Pub endpoints each cycle. If **any** probe fails → mirror env vars are set. If **all** probes succeed → mirrors are removed so Flutter uses defaults. This mirror logic is independent from DNS failover, so it still runs when the active DNS is a router or local proxy such as `192.168.x.x`.

| Status | Console | Action |
|--------|---------|--------|
| All probes OK | `Sanctions : LIFTED` | Remove tracked mirror env vars |
| Any probe fails | `Sanctions : ACTIVE` | Set mirror env vars from config |
| Already set | `Env mirrors : ACTIVE` | No change |
| Direct access, no mirrors | `Env mirrors : DIRECT` | No change |

**Env scope:** User-level vars are always applied. Machine-level vars are applied when running as Administrator (`env_scope: auto`).

**Important:** Only env vars that the tool itself set are removed on recovery — manually set values are never touched. Open terminals and IDEs (VS Code, Android Studio) must be **restarted** to pick up env changes; the current PowerShell session keeps old values.

**State tracking:** Applied vars are recorded in `state.json` under `env_applied` so the tool knows what to clean up.

### How it works

```
┌─────────────┐     every N min     ┌──────────────────────┐
│ Read DNS on │ ─────────────────▶│ Shecan DNS on adapter?│
│ active NIC  │                   └──────────┬───────────┘
└─────────────┘                              │
              ┌──────────────────────────────┼──────────────────────────┐
              ▼                              ▼                          ▼
         monitor_only                   failover + OK              failover + DOWN
         (no Shecan DNS)               → idle                     → backup DNS,
         → DDNS only, never            Shecan OK + fallback       prepend fallback,
           touch DNS settings          → restore from backup      keep router DNS
              │                              │                          │
              └──────────────────────────────┴──────────────────────────┘
                                           ▼
                              DDNS + IP check (if any DNS responds)
```

**Operating modes:**

| Mode | When | DNS changes |
|------|------|-------------|
| `monitor_only` | Active adapter has no Shecan DNS | Never |
| `failover` | Shecan DNS detected (`dns_failover: auto`) | Backup → add fallback → restore on recovery |

Before any DNS change, the tool saves your current DNS list to `state.json` (`dns_backup`) and restores it exactly when Shecan recovers. Router DNS (e.g. `192.168.1.1`) is preserved during failover.

**Failover order when Shecan is down:** `8.8.8.8` is placed **first** so Windows does not wait on dead Shecan servers.

**Default Shecan servers used by the tool:**

| Role | Address |
|------|---------|
| Primary | `178.22.122.101` |
| Secondary | `185.51.200.1` |
| Fallback | `8.8.8.8` |

### Sample output

**Monitor-only (no Shecan DNS on adapter):**

```
  Adapter        : Wi-Fi
  DNS configured : 192.168.1.1, 192.168.230.7
  Shecan DNS     : NO
  Mode           : monitor_only
  Shecan alive   : YES
  Update 1       : [OK] 203.0.113.42
```

**Normal operation (failover mode):**

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

**Sanctions active — mirror env vars set:**

```
  Sanctions      : ACTIVE
  Env mirrors    : SET [User] FLUTTER_STORAGE_BASE_URL, PUB_HOSTED_URL
  Env mirrors    : SET [Machine] FLUTTER_STORAGE_BASE_URL, PUB_HOSTED_URL
```

**Sanctions lifted — mirror env vars removed:**

```
  Sanctions      : LIFTED
  Env mirrors    : REMOVED [User] FLUTTER_STORAGE_BASE_URL, PUB_HOSTED_URL
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
- **Fallback scope** — Fallback DNS restores basic DNS; some filtered sites may not work until Shecan returns
- **Env var sessions** — Existing terminals/IDEs do not see env changes until restarted; new processes pick them up automatically
- **Tracked env only** — The tool only removes env vars it previously set; manual overrides are preserved
- **Probe vs Shecan alive** — Shecan TCP:53 may work while Google domains remain blocked, and a router/local DNS proxy may hide Shecan DNS from the adapter; HTTP probes are more accurate for dev mirrors

### Troubleshooting

**Internet stops working until I disable/enable the network adapter**

This was caused by the script overwriting DNS when Shecan was not configured, or restoring hardcoded Shecan IPs without preserving router DNS. Fixed in v2:

- If Shecan DNS is **not** on your adapter → **monitor_only** mode (no DNS changes)
- Stale `fallback_added` in `state.json` is cleared automatically
- Original DNS is backed up before failover and restored exactly on recovery

If you still have issues, delete `state.json` and restart the script. Pull the latest version from GitHub.

**Updates skipped but internet works**

The tool now checks whether **any** configured DNS server responds on port 53, not just Shecan. A temporary Shecan TCP failure no longer blocks DDNS when router DNS is working.

### Roadmap

- [ ] System tray / background mode
- [ ] Desktop notifications on outage/recovery
- [ ] Auto-start via Task Scheduler
- [ ] File logging
- [x] Configurable fallback DNS in `config.json`
- [x] Sanction mirror env vars for Flutter/Dart (auto probe + set/remove)
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
- متغیرهای محیطی mirror (Flutter/Dart) را بر اساس دسترسی به دامنه‌های واقعی تنظیم یا حذف می‌کند

> ابزار غیررسمی جامعه کاربری است و وابسته به تیم شکن نیست.

### ویژگی‌ها

- مانیتورینگ دوره‌ای DNS و سلامت سرورهای شکن
- Failover خودکار بدون وابستگی به DNS lookup
- پشتیبانی از چند URL به‌روزرسانی DDNS
- **Sanction mirror** — probe endpointهای واقعی Flutter/Pub و تنظیم/حذف خودکار `FLUTTER_STORAGE_BASE_URL` و `PUB_HOSTED_URL`
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

**اجرا با Admin برای failover DNS و scope Machine متغیرهای محیطی توصیه می‌شود. scope User بدون Admin هم کار می‌کند.**

### تنظیم DNS شکن

| نقش | آدرس |
|-----|------|
| اصلی | `178.22.122.101` |
| جایگزین | `185.51.200.1` |

### کانفیگ

فایل `config-sample.json` را به `config.json` کپی کنید. پسورد DDNS را از [پنل شکن](https://my.shecan.ir/panel/) بگیرید.

**هشدار امنیتی:** `config.json` را commit نکنید — در `.gitignore` قرار دارد.

- در صورت نبود DNS شکن روی آداپتر فعال → حالت **monitor_only** (بدون تغییر DNS)
- قبل از failover، DNS فعلی در `state.json` ذخیره و پس از برگشت شکن دقیقاً بازگردانده می‌شود

### Sanction mirror (Flutter / Dart)

به‌جای تنظیم دستی در هر ترمینال:

```powershell
$env:FLUTTER_STORAGE_BASE_URL = "https://flutter.devneeds.ir"
$env:PUB_HOSTED_URL = "https://dart.devneeds.ir"
```

ابزار هر سیکل endpointهای واقعی Flutter/Pub را probe می‌کند. اگر **همه** URLها در دسترس باشند → mirror حذف می‌شود. اگر **حتی یکی** fail شود → mirror اعمال می‌شود. این منطق مستقل از DNS failover است؛ بنابراین وقتی DNS فعال یک روتر یا DNS محلی مثل `192.168.x.x` باشد هم اجرا می‌شود.

| کلید | توضیح |
|------|-------|
| `sanction_mirrors.enabled` | `"auto"`/`"enabled"` = probe در هر سیکل؛ `"disabled"` = عدم تغییر env |
| `sanction_mirrors.probe_urls` | URLهای واقعی Flutter/Pub برای تست |
| `sanction_mirrors.env_vars` | نام متغیر → URL mirror |
| `sanction_mirrors.env_scope` | `"auto"` = User + Machine (با Admin) |

**نکات مهم:**
- ترمینال و IDE (VS Code، Android Studio) باید **restart** شوند تا env جدید را ببینند
- فقط متغیرهایی که خود tool set کرده حذف می‌شوند — مقادیر دستی دست نخورده می‌مانند
- Shecan ممکن است زنده باشد ولی Google هنوز block باشد، یا DNS روتر/محلی باعث شود IPهای شکن روی adapter دیده نشوند — probe HTTP دقیق‌تر است

### عیب‌یابی

**اینترنت قطع می‌شود تا کارت شبکه را disable/enable کنم**

در نسخه جدید، اگر DNS شکن روی سیستم نباشد اسکریپت DNS را تغییر نمی‌دهد. `state.json` قدیمی را پاک کنید و آخرین نسخه را اجرا کنید.

### محدودیت‌ها

- فقط ویندوز
- نیاز به Admin برای تغییر DNS و scope Machine متغیرهای محیطی
- ترمینال/IDE باز env قدیمی را نگه می‌دارد تا restart شود
- فقط یک instance همزمان اجرا شود
- در قطعی طولانی، `8.8.8.8` اینترنت را برمی‌گرداند اما ممکن است سایت‌های فیلترشده در دسترس نباشند

### مشارکت

Fork → branch → PR. از Conventional Commits استفاده کنید.

### مجوز

MIT — استفاده، تغییر و توزیع آزاد.
