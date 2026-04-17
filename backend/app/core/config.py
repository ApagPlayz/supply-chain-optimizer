from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Database
    DATABASE_URL: str = "sqlite:///./supply_chain.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Security — no default; must be set in .env
    # Generate with: python -c 'import secrets; print(secrets.token_hex(32))'
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # API
    DEBUG: bool = False
    PROJECT_NAME: str = "Supply Chain Intelligence Platform"
    API_V1_STR: str = "/api/v1"

    # CORS — comma-separated list of allowed origins (D-04)
    ALLOWED_ORIGINS: str = "http://localhost:5173,http://localhost:3000"

    # ── Mapping / Frontend ─────────────────────────────────────────────────────
    MAPBOX_API_KEY: str = ""

    # ── ACLED conflict data (free registration at acleddata.com) ──
    ACLED_EMAIL: str = ""
    ACLED_KEY: str = ""

    # ── Legacy data APIs (optional) ───────────────────────────────────────────
    FRED_API_KEY: str = ""
    EIA_API_KEY: str = ""
    ALPHA_VANTAGE_API_KEY: str = ""
    OPENWEATHER_API_KEY: str = ""

    # ── Nexar / Octopart (live component pricing — multi-distributor GraphQL) ──
    # Free evaluation: https://nexar.com/api
    # 1,000 part lookups on free eval; 2k/month Standard; 15k/month Pro
    # Uses OAuth2 client credentials → auto-refreshes bearer token
    NEXAR_CLIENT_ID: str = ""
    NEXAR_CLIENT_SECRET: str = ""

    # ── DigiKey API v4 (OAuth2 client credentials — free 1k/day) ─────────────
    # Register: https://developer.digikey.com/
    DIGIKEY_CLIENT_ID: str = ""
    DIGIKEY_CLIENT_SECRET: str = ""
    DIGIKEY_SANDBOX: bool = False   # set True to use sandbox while testing

    # ── OEMsecrets (40+ distributors in one call, free, approval-based) ──────
    # Adds breadth beyond Nexar's major distributors.
    # Apply: https://www.oemsecrets.com/api
    OEMSECRETS_API_KEY: str = ""

    # ── TrustedParts (authorized distributors only, completely free) ──────────
    # Register: https://www.trustedparts.com/docs/
    TRUSTEDPARTS_API_KEY: str = ""

    # ── EasyPost SmartRate (real transit times for VRP cost matrix) ───────────
    # Free: 500 SmartRate calls, then $0.03/call — https://www.easypost.com/
    EASYPOST_API_KEY: str = ""

    # ── SupplyMaven (macro disruption intelligence for Digital Twin) ──────────
    # GDI, disruption alerts, tariff data. Platform is $499/mo (pro).
    # Check https://supplymaven.com/developers for free tier availability.
    SUPPLYMAVEN_API_KEY: str = ""

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        """HARD-01: Reject known default values and weak keys at startup."""
        blocked = {
            "your-secret-key-change-in-production",
            "dev-secret-key-change-in-production",
            "secret",
            "changeme",
        }
        if v in blocked or len(v) < 32:
            raise ValueError(
                "SECRET_KEY is insecure. "
                "Set SECRET_KEY in .env to a random 64-char string: "
                "python -c 'import secrets; print(secrets.token_hex(32))'"
            )
        return v

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
