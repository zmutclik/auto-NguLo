# 🤖 Auto-NguLo — Panduan Instalasi & Pengoperasian

**Android Automation Manager** — Aplikasi web untuk membuat, mengelola, dan mengeksekusi script otomatisasi perangkat Android. Didesain untuk berjalan di lingkungan **Termux** (Android) dan dapat diakses melalui browser dari perangkat manapun.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-teal)
![License](https://img.shields.io/badge/license-MIT-orange)

---

## 📋 Daftar Isi

- [Prasyarat](#-prasyarat)
- [Instalasi](#-instalasi)
  - [1. Clone Project](#1-clone-project)
  - [2. Virtual Environment](#2-virtual-environment)
  - [3. Install Dependencies](#3-install-dependencies)
- [Konfigurasi](#-konfigurasi)
  - [Environment Variables](#environment-variables)
  - [File `.env`](#file-env)
- [Menjalankan Aplikasi](#-menjalankan-aplikasi)
  - [Cara 1: `start.sh` (recommended)](#cara-1-startsh-recommended)
  - [Cara 2: Manual](#cara-2-manual)
  - [Cara 3: Background Service (Termux:Boot)](#cara-3-background-service-termuxboot)
- [Akses Aplikasi](#-akses-aplikasi)
- [Login & Keamanan](#-login--keamanan)
- [Pengoperasian](#-pengoperasian)
  - [Dashboard — Kelola Script](#dashboard--kelola-script)
  - [Script Editor — Buat/Edit Script](#script-editor--buatedit-script)
  - [Menjalankan Script](#menjalankan-script)
  - [Live Log & Monitoring](#live-log--monitoring)
  - [History Eksekusi](#history-eksekusi)
  - [Settings — Ubah Password](#settings--ubah-password)
- [Jenis Action](#-jenis-action)
- [API Endpoints (Ringkasan)](#-api-endpoints-ringkasan)
- [Troubleshooting](#-troubleshooting)
- [Struktur Project](#-struktur-project)
- [Pengembangan](#-pengembangan)
- [Lisensi](#-lisensi)

---

## 📦 Prasyarat

| Kebutuhan | Versi / Keterangan |
|-----------|---------------------|
| **Python** | 3.10 atau lebih baru |
| **pip** | Sudah termasuk dalam Python |
| **venv** | Sudah termasuk dalam Python |
| **Termux** | Jika berjalan di Android (dari F-Droid, bukan Play Store) |
| **OS alternatif** | Linux, macOS, atau WSL |
| **Browser** | Chrome, Firefox, atau browser modern lainnya |

### Instalasi Termux (Android)

> ⚠️ Gunakan Termux dari **F-Droid**, bukan Google Play Store (versi Play Store sudah usang).

1. Download dan install [F-Droid](https://f-droid.org/)
2. Buka F-Droid, cari "Termux", lalu install
3. Buka Termux dan jalankan:
   ```bash
   pkg update && pkg upgrade
   pkg install python git
   ```

---

## 🚀 Instalasi

### 1. Clone Project

```bash
git clone <repo-url>
cd auto-NguLo
```

> Jika tidak menggunakan git, cukup ekstrak folder project ke direktori manapun.

### 2. Virtual Environment

```bash
python -m venv venv
source venv/bin/activate      # Linux / macOS / Termux
```

> Untuk Windows (cmd/PowerShell): `venv\Scripts\activate`

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

**Isi `requirements.txt`:**
```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
aiosqlite>=0.20.0
PyJWT>=2.8.0
httpx>=0.27.0
pydantic>=2.0.0
jinja2>=3.1.0
python-multipart>=0.0.9
aiofiles>=24.0.0
```

> Jika ada kendala instalasi `uvicorn` di Termux, jalankan:
> ```bash
> pkg install binutils build-essential python
> pip install --no-cache-dir uvicorn
> ```

---

## ⚙️ Konfigurasi

### Environment Variables

Semua konfigurasi menggunakan **environment variable**. Dapat diatur via file `.env` atau langsung di terminal.

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `ANGULO_HOST` | `0.0.0.0` | Host binding server (gunakan `0.0.0.0` agar bisa diakses dari LAN) |
| `ANGULO_PORT` | `8000` | Port server |
| `ANGULO_DEBUG` | `false` | Mode debug (log lebih detail) |
| `ANGULO_DB` | `data/angulo.db` | Path file database SQLite |
| `ANGULO_SECRET_KEY` | *(auto-generated)* | Secret key untuk JWT token |
| `ANGULO_JWT_EXPIRE` | `1440` | Masa berlaku token (menit), default 24 jam |
| `ANGULO_SCREENSHOT_DIR` | `data/screenshots` | Direktori penyimpanan screenshot |
| `ANGULO_TEMPLATE_DIR` | `data/templates` | Direktori template gambar untuk screenshot matching |
| `ANGULO_LOG_DIR` | `data/logs` | Direktori file log |
| `ANGULO_CORS` | `*` | CORS origins (pisahkan dengan koma untuk multi origin) |

### File `.env`

Buat file `.env` di root project:

```env
ANGULO_PORT=9000
ANGULO_SECRET_KEY=my-super-secret-key-2026
ANGULO_JWT_EXPIRE=60
ANGULO_DEBUG=true
```

---

## ▶️ Menjalankan Aplikasi

### Cara 1: `start.sh` (recommended)

```bash
chmod +x start.sh
./start.sh
```

Script ini otomatis:
- Membunuh proses server yang sedang berjalan di port yang dikonfigurasi
- Mengaktifkan virtual environment
- Menjalankan Uvicorn dengan **hot-reload** (auto-restart saat file berubah)

### Cara 2: Manual

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

| Flag | Keterangan |
|------|------------|
| `--host 0.0.0.0` | Mendengarkan di semua interface (wajib untuk akses LAN) |
| `--port 8000` | Port server |
| `--reload` | Auto-restart saat kode berubah (nonaktifkan di production) |

### Cara 3: Background Service (Termux:Boot)

Jalankan server sebagai background service agar otomatis menyala saat Termux boot:

```bash
# Install Termux:Boot dari F-Droid
# Buat script di ~/.termux/boot/
mkdir -p ~/.termux/boot
```

`~/.termux/boot/start-angulo`:
```bash
#!/data/data/com.termux/files/usr/bin/bash
cd /path/to/auto-NguLo
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 &
```

```bash
chmod +x ~/.termux/boot/start-angulo
```

---

## 🌐 Akses Aplikasi

Buka browser dan akses:

| Dari | URL |
|------|-----|
| **Device yang sama** | `http://localhost:8000` |
| **Device lain (LAN)** | `http://<IP-Device>:8000` |

### Cara Mengecek IP

```bash
# Di Termux / Linux
ifconfig wlan0        # atau
ip addr show wlan0    # atau
hostname -I
```

> 💡 Contoh: jika IP Termux adalah `192.168.1.10`, buka `http://192.168.1.10:8000` dari laptop atau HP lain.

### Testing API dari Terminal

```bash
# Login & ambil token
curl -s -X POST http://localhost:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"password":"123456"}'

# Cek status auth
curl http://localhost:8000/api/auth/check \
  -H 'Cookie: angulo_token=<TOKEN>'
```

---

## 🔐 Login & Keamanan

### Default Password

```
123456
```

> ⚠️ **WAJIB ganti password default** setelah login pertama! Buka halaman **Settings** untuk mengubahnya.

### Fitur Keamanan

- **JWT Token** disimpan di HTTP-only cookie (`ngulo_token`), tidak bisa diakses JavaScript → terlindungi dari XSS
- **Session 24 jam** — token expired otomatis setelah 1440 menit (bisa dikonfigurasi via `ANGULO_JWT_EXPIRE`)
- **Middleware auth** otomatis memeriksa semua route kecuali `/api/auth/login` dan static files
- **CORS** dapat dibatasi via `ANGULO_CORS`

---

## 🎮 Pengoperasian

### Dashboard — Kelola Script

Buka `/dashboard` setelah login.

| Aksi | Cara |
|------|------|
| **Buat script baru** | Klik tombol **"+ New Script"**, isi nama, deskripsi, repeat count & delay |
| **Edit script** | Klik nama script → masuk ke Script Editor |
| **Jalankan script** | Klik tombol ▶️ **Run** pada script |
| **Hapus script** | Klik tombol 🗑️ **Delete** pada script |

### Script Editor — Buat/Edit Script

Buka `/scripts/new` atau klik script dari Dashboard.

**Struktur Script:**
- **Nama & Deskripsi** — identitas script
- **Repeat** — berapa kali script diulang (1 = sekali jalan)
- **Repeat Delay (ms)** — jeda antar pengulangan dalam milidetik
- **Actions** — urutan langkah yang akan dieksekusi

**Menambah Action:**
1. Klik **"+ Add Action"**
2. Pilih tipe action (tap, swipe, type_text, dll.)
3. Isi parameter sesuai tipe action
4. Klik **Save Action**
5. Ulangi untuk action berikutnya

**Mengatur Urutan:**
- Klik ikon ⬆️⬇️ untuk memindahkan action naik/turun
- Urutan action menentukan urutan eksekusi

### Menjalankan Script

1. Dari **Dashboard**, klik ▶️ **Run** pada script yang ingin dijalankan
2. Anda akan dialihkan ke halaman **Execution** dengan live log
3. Script akan mengeksekusi actions satu per satu secara berurutan
4. Untuk **menghentikan** eksekusi yang sedang berjalan, klik tombol ⏹️ **Stop**

### Live Log & Monitoring

Halaman `/execute/{id}` menampilkan:

- **Status** — RUNNING / COMPLETED / FAILED / STOPPED
- **Progress** — action keberapa yang sedang dieksekusi
- **Live Log** — streaming real-time via SSE, setiap langkah tercatat:
  - Waktu eksekusi
  - Action yang dijalankan
  - Hasil (SUCCESS / FAIL)
  - Error message (jika gagal)
- **Statistik akhir** — total action sukses, gagal, durasi total

### History Eksekusi

Buka `/history` untuk melihat riwayat semua eksekusi:

- Daftar eksekusi terakhir (100 entries)
- Status tiap eksekusi (completed / failed / stopped)
- Statistik: jumlah action sukses vs gagal
- Durasi eksekusi
- Bisa **dihapus** satu per satu atau semua

### Settings — Ubah Password

Buka `/settings`:
1. Masukkan password saat ini
2. Masukkan password baru
3. Masukkan konfirmasi password baru
4. Klik **Save**

> Jika lupa password, hapus file `data/angulo.db` lalu restart server — password akan reset ke `123456`.

---

## 🎯 Jenis Action

Script terdiri dari urutan **action** yang dieksekusi berurutan. Berikut 10 jenis action yang didukung:

### 1. `tap` — Tap di koordinat
Tap layar di titik (x, y).
```
⚡ tap [Buka Aplikasi]
   📍 x: 540, y: 1200
```

### 2. `swipe` — Geser layar
Swipe dari (x1, y1) ke (x2, y2) dengan durasi.
```
⚡ swipe [Scroll ke Bawah]
   📍 540,1500 → 540,400 (500ms)
```

### 3. `long_press` — Tap tahan
Tap dan tahan di koordinat selama durasi tertentu.
```
⚡ long_press [Tahan Icon]
   📍 x: 200, y: 800 | ⏱ 1000ms
```

### 4. `screenshot_match` — Deteksi gambar
Cocokkan template image dengan screenshot layar. Mendukung retry dan jump.
```
⚡ screenshot_match [Cari Tombol Login]
   🖼 template: login_btn.png | 🎯 threshold: 0.80
   🔄 retry: 3x | ✅ jump: klik_login | ❌ jump: error_page
```

### 5. `wait` — Tunggu
Jeda eksekusi selama milidetik tertentu.
```
⚡ wait [Tunggu Loading]
   ⏱ 3000ms
```

### 6. `push_key` — Tekan tombol
Kirim key event Android (HOME, BACK, VOLUME_UP, dll).
```
⚡ push_key [Kembali]
   🔑 Key: BACK
```

### 7. `combo` — Kombinasi tombol
Jalankan key combo (select_all, copy, paste, cut, undo).
```
⚡ combo [Copy Text]
   🎮 Combo: copy
```

### 8. `fetch_api` — HTTP Request
Panggil API eksternal, simpan respon ke variabel.
```
⚡ fetch_api [Ambil Data]
   🌐 GET https://api.example.com/data
   💾 Save to: ${response_data}
```

### 9. `variable` — Operasi variabel
Set, update, atau get variabel runtime. Referensi dengan `${nama_var}`.
```
⚡ variable [Set Token]
   📝 ${auth_token} = "bearer-xxx"
```

### 10. `type_text` — Ketik teks
Simulasikan pengetikan karakter per karakter.
```
⚡ type_text [Isi Form]
   📝 "Hello World" | ⏱ 50ms/char
```

### Fitur Khusus Action

| Fitur | Deskripsi |
|-------|-----------|
| **`wait_before_ms`** | Jeda sebelum action dieksekusi |
| **`wait_after_ms`** | Jeda setelah action selesai |
| **`jump_on_success`** | Lompat ke action lain jika sukses |
| **`jump_on_fail`** | Lompat ke action lain jika gagal |
| **`use_match_result`** | Gunakan koordinat hasil screenshot_match untuk tap/swipe |
| **`${var_name}`** | Referensi variabel runtime dalam teks/URL/body |

---

## 🔌 API Endpoints (Ringkasan)

### Authentication
| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `POST` | `/api/auth/login` | Login dengan password, dapatkan token |
| `PUT` | `/api/auth/password` | Ubah password |
| `GET` | `/api/auth/check` | Cek status login |

### Scripts
| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `GET` | `/api/scripts` | List semua script |
| `POST` | `/api/scripts` | Buat script baru |
| `GET` | `/api/scripts/{id}` | Detail script + actions |
| `PUT` | `/api/scripts/{id}` | Update metadata script |
| `DELETE` | `/api/scripts/{id}` | Hapus script (cascade) |

### Actions
| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `GET` | `/api/scripts/{id}/actions` | List actions |
| `POST` | `/api/scripts/{id}/actions` | Tambah action |
| `PUT` | `/api/scripts/{id}/actions/{aid}` | Update action |
| `DELETE` | `/api/scripts/{id}/actions/{aid}` | Hapus action |

### Execution
| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `POST` | `/api/scripts/{id}/execute` | Jalankan script |
| `GET` | `/api/scripts/{id}/stream/{log_id}` | SSE live log |
| `POST` | `/api/scripts/{id}/stop` | Hentikan eksekusi |

### History
| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `GET` | `/api/history` | Riwayat eksekusi |
| `DELETE` | `/api/history` | Hapus semua history |
| `DELETE` | `/api/history/{log_id}` | Hapus satu entry |

---

## 🔧 Troubleshooting

| Masalah | Solusi |
|---------|--------|
| **Port sudah dipakai** | `pkill -f uvicorn` lalu jalankan ulang, atau ganti `ANGULO_PORT` |
| **Tidak bisa akses dari LAN** | Pastikan `ANGULO_HOST=0.0.0.0` dan firewall tidak memblokir port |
| **Database corrupt** | Hapus `data/angulo.db`, restart server (database baru akan dibuat otomatis) |
| **Lupa password** | Hapus `data/angulo.db` — password reset ke `123456` |
| **Token expired** | Login ulang; atau perpanjang `ANGULO_JWT_EXPIRE` |
| **Gagal install di Termux** | `pkg install binutils build-essential python` lalu `pip install --no-cache-dir -r requirements.txt` |
| **Halaman tidak muncul** | Cek konsol Uvicorn untuk error; pastikan semua file templates ada |
| **Script tidak berjalan** | Cek mode: saat ini **mock mode** — koordinat tap/swipe tidak benar-benar menyentuh layar |

---

## 📁 Struktur Project

```
auto-NguLo/
├── main.py                    # Entry point FastAPI + page routes
├── config.py                  # Konfigurasi (env vars)
├── requirements.txt           # Dependencies Python
├── start.sh                   # Script cepat untuk menjalankan server
│
├── database/
│   └── connection.py          # Koneksi async SQLite + schema
│
├── engine/
│   └── executor.py            # ScriptExecutor — eksekusi action
│
├── middleware/
│   └── auth_middleware.py      # JWT auth middleware
│
├── routers/
│   ├── auth.py                # Endpoint login & password
│   ├── scripts.py             # CRUD scripts
│   ├── actions.py             # CRUD actions
│   └── executor.py            # Eksekusi & SSE streaming
│
├── schemas/
│   └── requests.py            # Pydantic models
│
├── templates/                 # Jinja2 HTML (UI web)
│   ├── base.html              # Layout utama
│   ├── login.html             # Halaman login
│   ├── dashboard.html         # Daftar script
│   ├── script_editor.html     # Editor script
│   ├── execution.html         # Live log
│   ├── history.html           # Riwayat
│   └── settings.html          # Ubah password
│
├── data/                      # Runtime data (auto-created)
│   ├── angulo.db              # SQLite database
│   ├── templates/             # Screenshot templates
│   ├── screenshots/           # Hasil screenshot
│   └── logs/                  # File log
│
└── wireframes/                # Wireframe desain awal
```

---

## 🔧 Pengembangan

### Mode Mock vs Real

Saat ini executor berjalan dalam **mock mode** (`mock_mode=True` di `routers/executor.py`):
- Semua action Android **disimulasikan** — cocok untuk testing UI
- Screenshot matching selalu sukses dengan koordinat mock
- Tidak membutuhkan device Android atau ADB

Untuk mode **real** (produksi), perlu implementasi:
- ADB shell commands (`adb shell input tap/swipe/keyevent`)
- OpenCV untuk template matching (`cv2.matchTemplate`)
- UiAutomator2 untuk kontrol device Android

### Database Schema

| Tabel | Isi |
|-------|-----|
| `config` | Key-value store (password, settings) |
| `scripts` | Metadata script (nama, repeat, delay) |
| `actions` | Langkah script (tipe, koordinat, parameter) |
| `execution_logs` | Log hasil eksekusi (status, statistik, log JSON) |

---

## 📄 Lisensi

MIT License

---

**Dibuat dengan ❤️ untuk otomatisasi Android di Termux.**
