import os
from pathlib import Path


def _default_database_url() -> str:
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    # Railway Volume을 붙인 경우 별도 설정 없이 SQLite를 영구 저장소에 둡니다.
    volume_path = os.getenv("RAILWAY_VOLUME_MOUNT_PATH")
    if volume_path:
        db_path = Path(volume_path) / "vcu_products.db"
        return f"sqlite:///{db_path.as_posix()}"

    return "sqlite:///./vcu_products.db"


TARGET_SITE = os.getenv("TARGET_SITE", "https://vibecodinguniv.cafe24.com/").rstrip("/") + "/"
DATABASE_URL = _default_database_url()
CRAWL_INTERVAL_MINUTES = int(os.getenv("CRAWL_INTERVAL_MINUTES", "30"))
REQUEST_DELAY_SECONDS = float(os.getenv("REQUEST_DELAY_SECONDS", "0.08"))
REQUEST_TIMEOUT_SECONDS = float(os.getenv("REQUEST_TIMEOUT_SECONDS", "20"))
MAX_CATEGORY_PAGES = int(os.getenv("MAX_CATEGORY_PAGES", "20"))
MAX_PRODUCTS = int(os.getenv("MAX_PRODUCTS", "500"))
MAX_CONCURRENT_REQUESTS = int(os.getenv("MAX_CONCURRENT_REQUESTS", "6"))
INACTIVE_AFTER_MISSES = int(os.getenv("INACTIVE_AFTER_MISSES", "3"))
ENABLE_MANUAL_REFRESH = os.getenv("ENABLE_MANUAL_REFRESH", "true").lower() in {"1", "true", "yes", "on"}
AUTO_CRAWL_ON_STARTUP = os.getenv("AUTO_CRAWL_ON_STARTUP", "true").lower() in {"1", "true", "yes", "on"}
SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
APP_ENV = os.getenv("APP_ENV", "local")
