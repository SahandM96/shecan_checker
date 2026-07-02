# Shecan DNS Guardian

> **مهندس:** sahandm96
> **پلتفرم:** Windows (PowerShell + Python 3)
> **وضعیت:** عملیاتی

---

## فهرست

1. [مسئله](#مسئله)
2. [راهکار کلی](#راهکار-کلی)
3. [معماری پروژه](#معماری-پروژه)
4. [شرح کامپوننت‌ها](#شرح-کامپوننت‌ها)
   - [۱. ماژول DNS Reader](#۱-ماژول-dns-reader)
   - [۲. ماژول Health Checker](#۲-ماژول-health-checker)
   - [۳. ماژول DDNS Updater](#۳-ماژول-ddns-updater)
   - [۴. ماژول Fallback Manager](#۴-ماژول-fallback-manager)
   - [۵. ماژول IP Checker](#۵-ماژول-ip-checker)
   - [۶. State Manager](#۶-state-manager)
   - [۷. Config Loader](#۷-config-loader)
5. [فلو Diagram](#فلو-diagram)
6. [نحوه نصب و اجرا](#نحوه-نصب-و-اجرا)
7. [خروجی نمونه](#خروجی-نمونه)
8. [سناریوهای قطعی و عکس‌العمل سیستم](#سناریوهای-قطعی-و-عکسالعمل-سیستم)
9. [مشکلات شناخته شده](#مشکلات-شناخته-شده)
10. [رودمپ آینده](#رودمپ-آینده)

---

## مسئله

### شکن چکار میکند؟

شکن (Shecan) یک سرویس DNS تحریم‌شکن ایرانی است. کاربر DNS سیستم خود را به سرورهای شکن指向 می‌کند تا:

- تحریم‌های اینترنتی دور زده شوند
- دسترسی به سرویس‌های خارجی (GitHub, Google, Docker, npm, etc.) میسر شود
- سرعت دسترسی به CDN‌های داخلی افزایش یابد

### DNS شکن

| نقش | آدرس |
|------|-------|
| Primary | `178.22.122.101` |
| Secondary | `185.51.200.1` |

### مشکل اول: قطع شدن DNS شکن

سرورهای DNS شکن گاهی دچار اختلال می‌شوند (وقفه سرویس، timeout، packet loss). در این حالت:

1. ویندوز تلاش می‌کند به `178.22.122.101` متصل شود → **Timeout**
2. سپس به `185.51.200.1` → **Timeout**
3. در نهایت به `192.168.1.1` (مودم) → **Timeout**
4. نتیجه: **کل اینترنت قطع می‌شود** — `ERR_NAME_NOT_RESOLVED`

**ریشه:** شکن تنها Gateway DNS است. وقتی شکن down است، هیچ DNS fallback سریعی وجود ندارد.

### مشکل دوم: تغییر IP داینامیک

بسیاری از کاربران ایران IP داینامیک دارند. با هر بار تغییر IP (ریست مودم، قطع و وصل شدن)، شکن باید از IP جدید مطلع شود. در غیر این صورت:

- ترافیک کاربر به سرور اشتباه هدایت می‌شود
- اتصال شکن قطع می‌شود
- کاربر باید دستی وارد پنل شود و "اعلام IP" را بزند

---

## راهکار کلی

### سه وظیفه اصلی

```
┌──────────────────────────────────────────────┐
│             Shecan DNS Guardian                │
├──────────────────────────────────────────────┤
│  ۱. DNS Monitoring    │  تشخیص DNS سیستم و    │
│                       │  صحت سنجی شکن         │
├──────────────────────────────────────────────┤
│  ۲. DDNS Updater      │  به‌روزرسانی خودکار   │
│                       │  IP در سرور شکن       │
├──────────────────────────────────────────────┤
│  ۳. Fallback Manager  │  اضافه/حذف خودکار    │
│                       │  DNS backup هنگام قطعی│
└──────────────────────────────────────────────┘
```

---

## معماری پروژه

```
C:\workspace\shecan_checker\
├── shecan_tool.py          # هسته اصلی (همه ماژول‌ها)
├── config.json             # تنظیمات (update URLs, interval)
├── state.json              # وضعیت runtime (آیا fallback فعال است)
├── check_shecan.py         # نسخه اولیه (منسوخ)
├── run_checker.bat         # اجراکننده با دوبل کلیک
└── README.md               # این سند
```

### دیاگرام ارتباط ماژول‌ها

```
┌──────────────┐     ┌───────────────┐
│  Config      │────▶│  ShecanTool   │
│  (config.json│     │  (main loop)  │
└──────────────┘     └───────┬───────┘
                            │
              ┌─────────────┼─────────────┐
              │             │             │
              ▼             ▼             ▼
     ┌────────────┐ ┌────────────┐ ┌────────────┐
     │ DNS Reader │ │ Health     │ │ DDNS       │
     │ (PowerShell│ │ Checker    │ │ Updater    │
     │  + netsh)  │ │ (port 53)  │ │ (HTTP GET) │
     └────────────┘ └────────────┘ └────────────┘
                          │
                          ▼
                   ┌──────────────┐
                   │ Fallback     │
                   │ Manager      │
                   │ (set/remove  │
                   │  DNS via PS) │
                   └──────────────┘
                          │
                          ▼
                   ┌──────────────┐
                   │ State        │
                   │ (state.json) │
                   └──────────────┘
```

---

## شرح کامپوننت‌ها

### ۱. ماژول DNS Reader

```python
def get_configured_dns() -> list[str]
```

**وظیفه:** خواندن DNS Serverهای فعال در شبکه

**متد اجرا (۲ مرحله‌ای):**

| مرحله | ابزار | توضیح |
|-------|-------|--------|
| ۱ (Fast Path) | `PowerShell: Get-DnsClientServerAddress` | لیست DNS سرورهای IPv4 از همه آداپترهای غیرمجازی |
| ۲ (Fallback) | `netsh interface ip show dns` | اگر پاورشل timeout خورد (۵ ثانیه) |

**خروجی نمونه:** `["192.168.1.1", "178.22.122.101", "185.51.200.1"]`

**حالت‌های خطا:**
- پاورشل timeout → auto fallback به netsh
- netsh هم failed → لیست خالی برگردانده می‌شود
- هیچ آداپتری active نیست → لیست خالی

---

### ۲. ماژول Health Checker

```python
def is_shecan_alive() -> bool
```

**وظیفه:** بررسی زنده بودن DNS سرورهای شکن

**متد:**
- اتصال TCP به پورت 53 (DNS) سرورهای شکن
- اول `178.22.122.101` (timeout: ۵ ثانیه)
- اگر وصل نشد → `185.51.200.1`
- اگر هیچکدام وصل نشدند → شکن DOWN در نظر گرفته می‌شود

**چرا TCP port 53 و نه ping یا DNS lookup؟**
- پینگ ممکن است توسط فایروال بلوک شود
- DNS lookup خود وابسته به DNS است (circular dependency)
- TCP port 53 مستقل از DNS resolution کار می‌کند

---

### ۳. ماژول DDNS Updater

```python
def call_update_url(url: str) -> tuple[bool, str]
```

**وظیفه:** ارسال درخواست به لینک به‌روزرسانی شکن برای اعلام IP جدید

**لینک‌های به‌روزرسانی (پیکربندی در config.json):**

```
https://ddns.shecan.ir/update?password=0b0b6497ecdea05d
https://ddns.shecan.ir/update?password=f8557c3d386962c8
```

**نحوه کار:**
- GET request با User-Agent استاندارد
- پاسخ سرور: IP فعلی کاربر (مثل `5.217.181.13`)
- اگر پاسخ ۲۰۰ باشد → موفق
- اگر هر خطای دیگری → FAIL همراه با متن خطا

**تعداد:** ۲ لینک (برای دو سرویس/محصول مختلف در حساب شکن)

**مهم:** این مرحله فقط وقتی اجرا می‌شود که DNS کار کند (یا شکن alive باشد یا fallback 8.8.8.8 فعال باشد)

---

### ۴. ماژول Fallback Manager

این قلب هوشمند ابزار است.

```python
def set_dns_servers(interface_name: str, servers: list[str]) -> bool
```

**وظیفه:** مدیریت خودکار DNS سوم (Google 8.8.8.8) هنگام قطعی شکن

**شرایط فعال‌سازی:**

| وضعیت شکن | fallback فعال؟ | عکس‌العمل |
|-----------|---------------|------------|
| Alive     | خیر            | هیچ (stay idle) |
| Alive     | بله            | fallback حذف ← بازگشت به DNS شکن تنها |
| Dead      | خیر            | fallback اضافه ← `178.22.122.101, 185.51.200.1, 8.8.8.8` |
| Dead      | بله            | هیچ (قبلاً اضافه شده) |

**مکانیسم ذخیره وضعیت:**

```json
// state.json
{
  "fallback_added": true
}
```

این فایل بین سیکل‌ها و حتی بین ری‌استارت‌های اسکریپت پایدار می‌ماند.

**سناریوی کامل:**
1. `t=0`: شکن alive، fallback=false
2. `t=5min`: شکن still alive → هیچ
3. `t=10min`: شکن DEAD → **8.8.8.8 به DNS اضافه می‌شود**، fallback=true
4. `t=15min`: شکن still dead → fallback=true → هیچ (اینترنت به لطف 8.8.8.8 کار می‌کند)
5. `t=20min`: شکن ALIVE → **8.8.8.8 حذف می‌شود**، fallback=false، بازگشت به تنظیمات خالص شکن

**محدودیت:** تغییر DNS نیاز به **Admin Privileges** دارد.

---

### ۵. ماژول IP Checker

```python
def check_ip_service(url: str) -> tuple[bool, str]
```

**وظیفه:** نمایش IP فعلی عمومی از دید شکن

**آدرس:** `https://ip.shecan.ir/`

**خروجی نمونه:** `5.217.181.13`

**موارد استفاده:**
- تأیید اینکه ترافیک از طریق شکن مسیریابی می‌شود
- مقایسه IP بین سیکل‌ها برای تشخیص تغییر

---

### ۶. State Manager

```python
def load_state() -> dict
def save_state(state: dict) -> None
```

**وظیفه:** ذخیره و بازیابی وضعیت runtime

**فایل:** `state.json` (در کنار اسکریپت)

**داده‌های ذخیره شده:**
- `fallback_added: bool` — آیا fallback DNS فعال است؟

**چرا state.json؟**
- اگر اسکریپت کرش کند یا کاربر ببنددش، در اجرای بعدی می‌داند fallback فعال است یا نه
- از تغییرات بی‌مورد DNS جلوگیری می‌کند

---

### ۷. Config Loader

```python
def load_config() -> dict
```

**وظیفه:** بارگذاری تنظیمات از `config.json`

**اگر فایل وجود نداشته باشد:** با مقادیر پیش‌فرض ایجاد می‌کند

**این تنظیمات:**

| کلید | نوع | پیش‌فرض | توضیح |
|------|------|----------|--------|
| `update_urls` | `list[str]` | دو لینک شکن | لینک‌های DDNS برای به‌روزرسانی IP |
| `interval_minutes` | `int` | `5` | فاصله بین سیکل‌ها |
| `ip_check_url` | `str` | `https://ip.shecan.ir/` | سرویس تشخیص IP عمومی |

---

## فلو Diagram

```
[Start]
    │
    ▼
[Load Config & State]
    │
    ▼
┌──────────────────┐
│   CYCLE LOOP      │
│  (هر N دقیقه)     │
└──────────────────┘
    │
    ▼
[1. Read DNS from adapters] ─── PowerShell (۵s timeout)
    │                              └── netsh fallback
    ▼
[2. Check Shecan DNS in list?] ─── YES / NO
    │
    ▼
[3. Check Shecan alive?] ───────── TCP port 53
    │
    ▼
[4. Decision Matrix]
    │
    ├── Shecan YES + Alive YES + Fallback NO  → idle
    ├── Shecan YES + Alive NO  + Fallback NO  → ADD 8.8.8.8
    ├── Shecan YES + Alive YES + Fallback YES → REMOVE 8.8.8.8
    ├── Shecan YES + Alive NO  + Fallback YES → idle (already rescued)
    └── Shecan NO                             → alert user
    │
    ▼
[5. Re-read DNS] ─── تأیید اعمال تغییرات
    │
    ▼
[6. Call Update URLs] ─── فقط اگر DNS کار کند
    │
    ▼
[7. Check Public IP] ─── ip.shecan.ir
    │
    ▼
[Sleep N minutes] ─── goto cycle
```

---

## نحوه نصب و اجرا

### پیش‌نیازها

- Python 3.7+ (نصب شده در PATH)
- ویندوز ۱۰/۱۱ (با PowerShell 5.1)
- دسترسی Administrator برای تغییر DNS

### مراحل

```batch
:: ۱. کلون کنید (یا فایل‌ها را کپی کنید)
git clone https://github.com/sahandm96/shecan-guardian
cd shecan-guardian

:: ۲. کپی کانفیگ نمونه و ویرایش
copy config-sample.json config.json
:: حالا config.json را باز کنید و پسوردهای DDNS واقعی را وارد کنید

:: ۳. اجرا (حتماً as Administrator)
python shecan_tool.py
```

### گزینه‌های اجرا

| کامند | توضیح |
|-------|--------|
| `python shecan_tool.py` | اجرای loop بی‌نهایت با بازه تنظیم شده |
| `python shecan_tool.py --once` | یک سیکل اجرا کن و خروج |
| `run_checker.bat` | دوبل کلیک (باز شدن CMD و اجرا) |

### تنظیم DNS دستی (اولیه)

اگر DNS سیستم روی شکن تنظیم نیست، قبلش دستی تنظیم کنید:

1. Control Panel → Network and Sharing Center → Change adapter settings
2. راست کلیک روی Wi-Fi/Ethernet → Properties
3. Internet Protocol Version 4 (TCP/IPv4) → Properties
4. گزینه "Use the following DNS server addresses"
5. Preferred: `178.22.122.101`
6. Alternate: `185.51.200.1`
7. OK

---

## خروجی نمونه

### حالت عادی (شکن فعال)

```
============================================================
[2026-07-02 16:10:00] Cycle 12
  DNS configured : 192.168.1.1, 178.22.122.101, 185.51.200.1
  Shecan DNS     : YES
  Shecan alive   : YES
  DNS current    : 192.168.1.1, 178.22.122.101, 185.51.200.1
  Update 1      : [OK] 5.217.181.13
  Update 2      : [OK] 5.217.181.13
  IP check       : [OK] 5.217.181.13
```

### قطعی شکن + فعال شدن fallback

```
============================================================
[2026-07-02 16:15:00] Cycle 13
  DNS configured : 192.168.1.1, 178.22.122.101, 185.51.200.1
  Shecan DNS     : YES
  Shecan alive   : NO
  DNS fallback   : ADDED 8.8.8.8
  DNS current    : 192.168.1.1, 178.22.122.101, 185.51.200.1, 8.8.8.8
  Update 1      : [OK] 5.217.181.13
  Update 2      : [OK] 5.217.181.13
  IP check       : [OK] 5.217.181.13
```

### بازگشت شکن + حذف fallback

```
============================================================
[2026-07-02 16:20:00] Cycle 14
  DNS configured : 192.168.1.1, 178.22.122.101, 185.51.200.1
  Shecan DNS     : YES
  Shecan alive   : YES
  DNS fallback   : REMOVED
  DNS current    : 192.168.1.1, 178.22.122.101, 185.51.200.1
  Update 1      : [OK] 5.217.181.13
  Update 2      : [OK] 5.217.181.13
  IP check       : [OK] 5.217.181.13
```

### قطعی کامل DNS (حتی 8.8.8.8 هم کار نمی‌کند)

```
============================================================
[2026-07-02 16:25:00] Cycle 15
  DNS configured : 192.168.1.1, 178.22.122.101, 185.51.200.1
  Shecan DNS     : YES
  Shecan alive   : NO
  DNS fallback   : ACTIVE (8.8.8.8 added)
  DNS current    : 192.168.1.1, 178.22.122.101, 185.51.200.1, 8.8.8.8
  Update 1      : [FAIL] <urlopen error [Errno 11001] getaddrinfo failed>
  Update 2      : [FAIL] <urlopen error [Errno 11001] getaddrinfo failed>
  IP check       : [FAIL] <urlopen error [Errno 11001] getaddrinfo failed>
```

---

## سناریوهای قطعی و عکس‌العمل سیستم

### سناریو ۱: قطع مقطعی DNS شکن (معمول)

**مدت:** ۳۰ ثانیه تا ۵ دقیقه

**واکنش سیستم:**
```
t+0:  Shecan dead → ADD fallback
t+5:  Shecan still dead → fallback active → اینترنت سالم
t+10: Shecan alive → REMOVE fallback
```

**نتیجه:** کاربر متوجه قطعی نمی‌شود. DNS شکن پشت پرده fallback می‌خورد.

---

### سناریو ۲: قطع طولانی شکن (ساعت‌ها)

**واکنش سیستم:**
```
t+0:   ADD fallback
t+5:   fallback active
t+60:  fallback active
...
t+300: fallback active (تا وقتی شکن برگردد)
```

**نتیجه:** تا برگشتن شکن، از Google DNS استفاده می‌کند. دسترسی به سایت‌های خارجی ممکن است محدود شود (تحریم), اما اینترنت قطع نمی‌شود.

---

### سناریو ۳: تغییر IP (ریست مودم)

**واکنش سیستم:**
```
Update 1: [OK] 5.217.181.13    (IP قبلی)
Update 1: [OK] 5.217.181.14    (IP جدید — شکن از IP جدید مطلع شد)
```

**نتیجه:** IP جدید به سرور شکن اعلام شد. اتصال شکن پایدار می‌ماند.

---

### سناریو ۴: DNS دستی حذف شد (رفتن به تنظیمات و تغییر DNS)

**خروجی:**
```
  DNS configured : 192.168.1.1
  Shecan DNS     : NO
```

**واکنش:** ابزار هشدار می‌دهد اما DNS را بازگردانی نمی‌کند (فعلاً فقط مانیتورینگ).

---

## مشکلات شناخته شده

### ۱. Timeout در خواندن DNS با PowerShell

**علت:** برخی آداپترهای مجازی (VirtualBox, Hyper-V, VMware) باعث کندی پاسخ PowerShell می‌شوند.

**راهکار فعلی:** Timeout ۵ ثانیه + Fallback به `netsh`.

**راهکار آینده:** فیلتر دقیق‌تر آداپترها با InterfaceMetric.

---

### ۲. getaddrinfo failed پس از قطع DNS

**علت:** وقتی همه DNS‌ها failed می‌شوند (حتی 8.8.8.8)، تا ۲-۳ دقیقه طول می‌کشد تا DNS cache ویندوز ریفرش شود.

**راهکار فعلی:** ابزار صبر می‌کند و سیکل بعدی دوباره تلاش می‌کند.

---

### ۳. Admin Rights Required

**علت:** تغییر DNS با `Set-DnsClientServerAddress` نیاز به admin دارد.

**راهکار فعلی:** پیام خطا چاپ می‌شود و fallback اضافه نمی‌شود.

---

### ۴. هم‌زمانی دو instance

**علت:** اگر دو پنجره از اسکریپت همزمان اجرا شوند، state.json دچار race condition می‌شود.

**راهکار فعلی:** ندارد — توصیه می‌شود فقط یک instance اجرا شود.

---

## رودمپ آینده

### اولویت بالا

- [ ] **System Tray Mode** — اجرا در پس‌زمینه با آیکون notification area
- [ ] **Desktop Notification** — Push notification هنگام قطع/وصل شکن
- [ ] **Auto-start with Windows** — اضافه به Startup folder یا Task Scheduler
- [ ] **Log to File** — ذخیره تمام تاریخچه در `shecan.log`

### اولویت متوسط

- [ ] **Web Dashboard** — نمایش وضعیت لحظه‌ای و تاریخچه در یک صفحه HTML ساده
- [ ] **Telegram/Email Alert** — ارسال نوتیفیکیشن قطعی به پیام‌رسان
- [ ] **DNS Test Suite** — تست سرعت و latency DNS شکن vs. بقیه
- [ ] **Multi-config Support** — پشتیبانی از چند اکانت شکن

### اولویت پایین

- [ ] **GUI Settings Panel** — تنظیمات بصری به جای config.json
- [ ] **Linux Support** — پورت به systemd-resolved / resolvconf
- [ ] **Docker Container** — اجرا در کانتینر برای سرور
- [ ] **Auto DNS Setup** — تنظیم خودکار DNS شکن روی آداپتر (اگر فعال نیست)

---

## فایل‌های کانفیگ

### `config-sample.json` — نمونه برای کپی کردن

```json
{
  "update_urls": [
    "https://ddns.shecan.ir/update?password=YOUR_PASSWORD_HERE",
    "https://ddns.shecan.ir/update?password=YOUR_SECOND_PASSWORD_HERE"
  ],
  "interval_minutes": 5,
  "ip_check_url": "https://ip.shecan.ir/"
}
```

**نحوه استفاده:**
1. `config-sample.json` را کپی کنید به `config.json`
2. `YOUR_PASSWORD_HERE` را با پسورد واقعی که از پنل شکن گرفتی عوض کن
3. اگر یک لینک داری، لینک دوم را پاک کن (یا بگذار برای اکانت دوم)

### `config.json` — فایل واقعی (محرمانه)

> **⚠️ امنیت:** این فایل شامل پسوردهای DDNS شماست. هرگز آن را commit نکنید.
> 
> `.gitignore` از قبل تنظیم شده تا `config.json` و `state.json` را نادیده بگیرد.

### `.gitignore`

```gitignore
# Sensitive config
config.json
state.json

# Python
__pycache__/
*.pyc
*.pyo
```

---

## License

MIT — استفاده آزاد، ویرایش آزاد، share کنید.

---

<div dir="rtl">

**ساخته شده با ☕ توسط sahandm96**  
> این ابزار برای استفاده شخصی توسعه داده شده و تضمینی برای uptime 100% ندارد.  
> همیشه یک fallback DNS دستی هم داشته باشید.

</div>
