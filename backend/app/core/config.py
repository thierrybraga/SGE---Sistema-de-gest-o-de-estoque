import os
from datetime import timedelta

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")

def _resolve_database():
    direct = os.environ.get("DATABASE")
    if direct:
        return direct
    url = os.environ.get("DATABASE_URL", "")
    if url:
        if url.startswith("sqlite:////"):
            return "/" + url[len("sqlite:////"):]
        if url.startswith("sqlite:///"):
            path = url[len("sqlite:///"):]
            return path if path.startswith("/") else "/" + path
        raise ValueError("DATABASE_URL deve usar sqlite:/// para POC")
    if os.environ.get("DYNO"):
        return "/tmp/stock.db"
    return os.path.join(DATA_DIR, "stock.db")

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "stock-enterprise-secret-2024")
    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "jwt-stock-secret-2024")
    MAX_CONTENT_LENGTH = 32 * 1024 * 1024  # 32MB para suportar PDFs
    DATABASE = _resolve_database()
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False

class TestingConfig(Config):
    TESTING = True
    DATABASE = ":memory:"

config_map = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
