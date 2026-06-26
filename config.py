"""
Auto-NguLo Configuration
Reads from environment variables with sensible defaults for Termux deployment.
"""
import os

# ---- Server ----
HOST = os.getenv("ANGULO_HOST", "0.0.0.0")
PORT = int(os.getenv("ANGULO_PORT", "8000"))
DEBUG = os.getenv("ANGULO_DEBUG", "false").lower() == "true"

# ---- Database ----
DATABASE_PATH = os.getenv("ANGULO_DB", "data/angulo.db")

# ---- Auth ----
# Default password stored as bcrypt hash of "123456"
# Generated at runtime if not set
DEFAULT_PASSWORD = "123456"
SECRET_KEY = os.getenv("ANGULO_SECRET_KEY", "auto-ngulo-secret-key-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("ANGULO_JWT_EXPIRE", "1440"))  # 24 hours

# ---- Automation ----
SCREENSHOT_DIR = os.getenv("ANGULO_SCREENSHOT_DIR", "data/screenshots")
TEMPLATE_DIR = os.getenv("ANGULO_TEMPLATE_DIR", "data/templates")
LOG_DIR = os.getenv("ANGULO_LOG_DIR", "data/logs")

# ---- CORS (for remote access) ----
CORS_ORIGINS = os.getenv("ANGULO_CORS", "*").split(",")
