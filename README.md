# 🤖 Auto-NguLo

**Android Automation Manager** — Aplikasi web untuk membuat, mengelola, dan mengeksekusi script otomatisasi perangkat Android. Didesain untuk berjalan di lingkungan **Termux** (Android) dan dapat diakses melalui browser dari perangkat manapun.

![Version](https://img.shields.io/badge/version-1.0.0-blue)
![Python](https://img.shields.io/badge/python-3.10+-green)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-teal)
![License](https://img.shields.io/badge/license-MIT-orange)

---

## 📋 Daftar Isi

- [Fitur](#-fitur)
- [Tech Stack](#-tech-stack)
- [Struktur Project](#-struktur-project)
- [Instalasi](#-instalasi)
- [Menjalankan Aplikasi](#-menjalankan-aplikasi)
- [Konfigurasi](#-konfigurasi)
- [API Endpoints](#-api-endpoints)
- [Jenis Action](#-jenis-action)
- [Halaman Web](#-halaman-web)
- [Keamanan](#-keamanan)
- [Pengembangan](#-pengembangan)
- [Roadmap](#-roadmap)

---

## ✨ Fitur

| Fitur | Deskripsi |
|-------|-----------|
| 🔐 **Auth Sederhana** | Login hanya dengan password (tanpa username), JWT token 24 jam |
| 📝 **Script Editor** | Buat dan edit script otomatisasi dengan UI interaktif |
| ⚡ **10 Jenis Action** | Tap, swipe, long press, screenshot match, type text, key event, combo, API call, variable, wait |
| 🔄 **Repeat Loop** | Jalankan script berulang kali dengan jeda antar pengulangan |
| 🎯 **Jump Logic** | Lompat ke action tertentu berdasarkan sukses/gagal |
| 📸 **Screenshot Matching** | Deteksi elemen UI via template image dengan retry |
| 🌐 **API Integration** | Panggil HTTP API dan simpan respon ke variabel |
| 📊 **Live Log SSE** | Streaming log eksekusi real-time via Server-Sent Events |
| 📜 **Execution History** | Riwayat semua eksekusi script dengan statistik |
| 🎨 **Dark UI Modern** | Interface Tailwind CSS + Alpine.js, dark theme |
| 📱 **Termux Ready** | Didesain untuk berjalan di Android via Termux |
| 🧪 **Mock Mode** | Simulasi eksekusi tanpa device Android (untuk development) |

---

## 🛠 Tech Stack

| Layer | Teknologi |
|-------|-----------|
| **Backend** | Python 3.10+, FastAPI |
| **Server** | Uvicorn (ASGI) |
| **Database** | SQLite (aiosqlite — async) |
| **Auth** | PyJWT (HS256) |
| **Template** | Jinja2 |
| **Frontend** | Tailwind CSS, Alpine.js (CDN) |
| **HTTP Client** | httpx (async) |
| **Validasi** | Pydantic v2 |

---

## 📁 Struktur Project

```
auto-NguLo/
├── main.py                    # Entry point FastAPI app + page routes
├── config.py                  # Konfigurasi (env vars)
├── requirements.txt           # Dependencies Python
├── start.sh                   # Script untuk menjalankan server
│
├── database/
│   ├── __init__.py
│   └── connection.py          # Async SQLite connection + schema init
│
├── engine/
│   ├── __init__.py
│   └── executor.py            # ScriptExecutor — menjalankan action script
│
├── middleware/
│   ├── __init__.py
│   └── auth_middleware.py      # JWT auth middleware + helper functions
│
├── routers/
│   ├── __init__.py
│   ├── auth.py                # POST /api/auth/login, PUT /api/auth/password
│   ├── scripts.py             # CRUD /api/scripts
│   ├── actions.py             # CRUD /api/scripts/{id}/actions
│   └── executor.py            # POST /execute, GET /stream (SSE)
│
├── schemas/
│   ├── __init__.py
│   └── requests.py            # Pydantic models (request/response)
│
├── templates/                 # Jinja2 HTML templates
│   ├── base.html              # Layout utama (navbar, styling)
│   ├── login.html             # Halaman login
│   ├── dashboard.html         # Daftar script
│   ├── script_editor.html     # Editor script + actions
│   ├── execution.html         # Live log eksekusi
│   ├── history.html           # Riwayat eksekusi
│   └── settings.html          # Ubah password
│
├── data/                      # Runtime data (auto-created)
│   ├── angulo.db              # SQLite database
│   ├── templates/             # Screenshot templates (static mount)
│   ├── screenshots/           # Screenshot hasil capture
│   └── logs/                  # File log
│
└── wireframes/                # Wireframe HTML (desain awal)
    ├── dashboard.html
    ├── execution.html
    ├── history.html
    ├── login.html
    ├── script-editor.html
    └── settings.html
```

---

## 🚀 Instalasi

### Prasyarat

- **Python 3.10+**
- **Termux** (jika di Android) atau Linux/macOS
- `pip` dan `venv`

### Langkah Instalasi

```bash
# 1. Clone repository
git clone <repo-url>
cd auto-NguLo

# 2. Buat virtual environment
python -m venv venv

# 3. Aktifkan virtual environment
source venv/bin/activate      # Linux/macOS/Termux

# 4. Install dependencies
pip install -r requirements.txt
```

---

## ▶️ Menjalankan Aplikasi

### Cara 1: Menggunakan `start.sh`

```bash
chmod +x start.sh
./start.sh
```

Script ini akan:
- Membunuh proses server yang sedang berjalan di port 8000
- Menjalankan Uvicorn dengan hot-reload (auto-restart saat file berubah)

### Cara 2: Manual

```bash
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Akses Aplikasi

Buka browser dan akses:
- **Dari device yang sama:** `http://localhost:8000`
- **Dari device lain (LAN):** `http://<IP-Termux>:8000`

> 💡 Cek IP Termux: `ifconfig wlan0` atau `ip addr show wlan0`

### Default Password

```
123456
```

> ⚠️ **Ganti password default** melalui halaman Settings setelah login pertama!

---

## ⚙️ Konfigurasi

Semua konfigurasi menggunakan **environment variable**. Dapat diatur via `.env` file atau langsung di terminal.

| Variable | Default | Deskripsi |
|----------|---------|-----------|
| `ANGULO_HOST` | `0.0.0.0` | Host binding server |
| `ANGULO_PORT` | `8000` | Port server |
| `ANGULO_DEBUG` | `false` | Mode debug |
| `ANGULO_DB` | `data/angulo.db` | Path database SQLite |
| `ANGULO_SECRET_KEY` | `auto-ngulo-secret-key-...` | Secret key JWT |
| `ANGULO_JWT_EXPIRE` | `1440` | Expire token (menit, default 24 jam) |
| `ANGULO_SCREENSHOT_DIR` | `data/screenshots` | Direktori screenshot |
| `ANGULO_TEMPLATE_DIR` | `data/templates` | Direktori template image |
| `ANGULO_LOG_DIR` | `data/logs` | Direktori log |
| `ANGULO_CORS` | `*` | CORS origins (comma-separated) |

Contoh `.env`:

```env
ANGULO_PORT=9000
ANGULO_SECRET_KEY=my-super-secret-key-2026
ANGULO_JWT_EXPIRE=60
```

---

## 🔌 API Endpoints

### 🔐 Authentication

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `POST` | `/api/auth/login` | Login dengan password |
| `PUT` | `/api/auth/password` | Ganti password |
| `GET` | `/api/auth/check` | Cek status autentikasi |

**Login Request:**
```json
{ "password": "123456" }
```

**Login Response:**
```json
{ "token": "eyJ...", "message": "Login successful" }
```

### 📝 Scripts CRUD

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `GET` | `/api/scripts` | List semua script (+ action count) |
| `POST` | `/api/scripts` | Buat script baru |
| `GET` | `/api/scripts/{id}` | Detail script + actions |
| `PUT` | `/api/scripts/{id}` | Update script |
| `DELETE` | `/api/scripts/{id}` | Hapus script (cascade actions) |

### ⚡ Actions CRUD

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `GET` | `/api/scripts/{id}/actions` | List actions dalam script |
| `POST` | `/api/scripts/{id}/actions` | Tambah action |
| `GET` | `/api/scripts/{id}/actions/{aid}` | Detail action |
| `PUT` | `/api/scripts/{id}/actions/{aid}` | Update action |
| `DELETE` | `/api/scripts/{id}/actions/{aid}` | Hapus action |
| `PUT` | `/api/scripts/{id}/actions/reorder` | Reorder actions |

### 🚀 Execution

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `POST` | `/api/scripts/{id}/execute` | Jalankan script |
| `GET` | `/api/scripts/{id}/stream/{log_id}` | Stream log via SSE |
| `POST` | `/api/scripts/{id}/stop` | Hentikan eksekusi |

### 📜 History

| Method | Endpoint | Deskripsi |
|--------|----------|-----------|
| `GET` | `/api/history` | Semua execution history (100 terakhir) |
| `DELETE` | `/api/history` | Hapus semua history |
| `DELETE` | `/api/history/{log_id}` | Hapus satu entry |

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
Swipe dari (x, y) ke (x2, y2) dengan durasi.
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
Cocokkan template image dengan screenshot layar. Mendukung retry dan jump logic.
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
Set, update, atau get variabel runtime. Variabel bisa direferensi dengan `${nama_var}`.
```
⚡ variable [Set Token]
   📝 ${auth_token} = "bearer-xxx"

⚡ variable [Get Token]
   📝 Get ${auth_token}
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

## 🌐 Halaman Web

| Halaman | Route | Deskripsi |
|---------|-------|-----------|
| **Login** | `/` | Halaman login dengan password |
| **Dashboard** | `/dashboard` | Daftar semua script, buat/hapus script |
| **Script Editor** | `/scripts/new` | Buat script baru + atur urutan actions |
| **Edit Script** | `/scripts/{id}/edit` | Edit script yang sudah ada |
| **Execution** | `/execute/{id}` | Live log SSE saat eksekusi berjalan |
| **History** | `/history` | Riwayat semua eksekusi dengan statistik |
| **Settings** | `/settings` | Ubah password aplikasi |
| **Logout** | `/logout` | Hapus cookie & redirect ke login |

---

## 🔒 Keamanan

- **JWT Token** disimpan di HTTP-only cookie (`ngulo_token`), tidak bisa diakses JavaScript
- **Password** disimpan di database SQLite (plaintext — akan diupgrade ke bcrypt di versi berikutnya)
- **Middleware auth** otomatis memeriksa semua route kecuali `/api/auth/login` dan static files
- **CORS** dapat dikonfigurasi via `ANGULO_CORS` untuk membatasi origin
- **Session 24 jam** — token expired setelah 1440 menit (dapat diubah)

---

## 🔧 Pengembangan

### Mode Mock vs Real

Saat ini executor berjalan dalam **mock mode** (`mock_mode=True` di `routers/executor.py`). Dalam mode ini:
- Semua action Android disimulasikan (tidak butuh device/ADB)
- Screenshot matching selalu sukses dengan koordinat mock
- Cocok untuk development dan testing UI

Untuk mode real (produksi), perlu implementasi:
- ADB shell commands (`adb shell input tap/swipe/keyevent`)
- OpenCV untuk template matching (`cv2.matchTemplate`)
- UiAutomator2 untuk kontrol device

### Menambah Jenis Action Baru

1. Tambahkan validasi di `schemas/requests.py` → `action_type` pattern
2. Tambahkan handler di `engine/executor.py` → method `execute()`
3. Tambahkan UI di `templates/script_editor.html`

### Database Schema

Database SQLite terdiri dari 4 tabel:
- **`config`** — key-value store (password, settings)
- **`scripts`** — metadata script (nama, repeat, delay)
- **`actions`** — langkah-langkah script (tipe, koordinat, parameter)
- **`execution_logs`** — log hasil eksekusi (status, statistik, log JSON)

---

## 🗺 Roadmap

- [ ] Bcrypt hashing untuk password
- [ ] ADB integration (real device control)
- [ ] OpenCV template matching (real screenshot match)
- [ ] Upload screenshot template via UI
- [ ] Drag-and-drop reorder actions
- [ ] Export/import script (JSON)
- [ ] Multi-user support
- [ ] WebSocket untuk live log (ganti SSE)
- [ ] Docker support
- [ ] Background service (Termux: Boot)

---

## 📄 Lisensi

MIT License

---

**Dibuat dengan ❤️ untuk otomatisasi Android di Termux.**
