from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./converge.db"
    cookie_secure: bool = False
    frontend_origin: str = "http://localhost:5173"
    daily_salt: str = "development-only-salt"
    seed_demo: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
