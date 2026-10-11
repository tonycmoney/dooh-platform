from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent

DEV_PASSWORD = "change-me"
DEV_SECRET = "dev-secret-change-me"
MIN_PASSWORD_LENGTH = 12


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # "production" turns on the startup safety checks and HSTS.
    environment: str = "development"

    database_url: str = "postgresql+psycopg://localhost/dooh"
    media_dir: Path = REPO_DIR / "media"  # formatted files, public at /files
    originals_dir: Path = REPO_DIR / "originals"  # original uploads, never served
    admin_password: str = DEV_PASSWORD
    secret_key: str = DEV_SECRET
    admin_token_days: int = 30

    # Built dashboard (dashboard/dist). Served at / when the folder exists.
    dashboard_dir: Path = REPO_DIR / "dashboard" / "dist"

    # Daily pg_dump of the database, kept for backup_keep_days.
    daily_backups: bool = False
    backup_dir: Path = REPO_DIR / "backups"
    backup_keep_days: int = 14

    # Customer website orders (POST /api/website/orders). The website sends
    # this key; files are only downloaded over HTTPS from these host suffixes.
    website_api_key: str = ""
    order_file_hosts: str = ".supabase.co"
    order_file_max_bytes: int = 200 * 2**20
    # Signing secret of the Stripe webhook endpoint (whsec_...); payments are
    # matched to website orders by client_reference_id.
    stripe_webhook_secret: str = ""

    # Email (Resend's HTTPS API; Railway's Hobby plan blocks SMTP).
    resend_api_key: str = ""
    alert_email_to: str = ""  # comma-separated
    alert_email_from: str = "DOOH Alerts <onboarding@resend.dev>"
    public_url: str = ""  # dashboard address, for links in emails

    # Alerts and the daily report (the monitor runs when monitoring is on).
    monitoring: bool = False
    alert_offline_minutes: int = 10
    alert_not_playing_minutes: int = 10
    timezone: str = "America/New_York"
    daily_report_hour: int = 7  # local time; covers the previous day

    # A screen counts as offline after this many seconds without a heartbeat
    # (3 missed heartbeats at the 60 s interval).
    offline_after_seconds: int = 180
    default_item_seconds: int = 10

    @field_validator("database_url")
    @classmethod
    def _use_psycopg3(cls, url: str) -> str:
        # Hosts hand out postgres:// or postgresql:// URLs; SQLAlchemy needs
        # the driver named to use psycopg 3.
        for prefix in ("postgres://", "postgresql://"):
            if url.startswith(prefix):
                return "postgresql+psycopg://" + url[len(prefix):]
        return url

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def libpq_database_url(self) -> str:
        """The database URL in the form pg_dump and psql understand."""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)

    def production_problems(self) -> list[str]:
        problems = []
        if self.admin_password == DEV_PASSWORD or len(self.admin_password) < MIN_PASSWORD_LENGTH:
            problems.append(f"ADMIN_PASSWORD must be set to at least {MIN_PASSWORD_LENGTH} characters")
        if self.secret_key == DEV_SECRET or len(self.secret_key) < 32:
            problems.append("SECRET_KEY must be set to a random string of at least 32 characters")
        if self.website_api_key and len(self.website_api_key) < 32:
            problems.append("WEBSITE_API_KEY must be at least 32 characters (or unset to turn website orders off)")
        return problems

    def resolved_media_dir(self) -> Path:
        return _ensure_dir(self.media_dir)

    def resolved_originals_dir(self) -> Path:
        return _ensure_dir(self.originals_dir)

    def resolved_backup_dir(self) -> Path:
        return _ensure_dir(self.backup_dir)


def _ensure_dir(path: Path) -> Path:
    if not path.is_absolute():
        path = (BACKEND_DIR / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


settings = Settings()
