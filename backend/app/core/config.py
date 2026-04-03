from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Database
    DATABASE_URL: str = "postgresql://logistics_user:logistics_password@localhost:5432/logistics_db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Security
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # API
    DEBUG: bool = True
    PROJECT_NAME: str = "Supply Chain Intelligence Platform"
    API_V1_STR: str = "/api/v1"

    # External APIs
    FRED_API_KEY: str = ""
    EIA_API_KEY: str = ""
    ALPHA_VANTAGE_API_KEY: str = ""
    OPENWEATHER_API_KEY: str = ""
    MAPBOX_API_KEY: str = ""

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
