from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./converge.db"
    app_env: Literal["local", "staging", "production"] = "local"
    deployment_id: str = "converge-local"
    app_version: str = "development"
    cookie_secure: bool = False
    frontend_origin: str = "http://localhost:5173"
    daily_salt: str = "development-only-salt"
    recent_target_window: int = 30
    seed_demo: bool = False
    admin_session_secret: str = "local-admin-session-secret-change-me"
    admin_password: str = "replace-with-a-long-random-password"
    operator_job_poll_seconds: float = 2.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


    def validate_runtime(self) -> None:
        if not self.deployment_id.strip():
            raise RuntimeError("DEPLOYMENT_ID is required")
        if self.recent_target_window < 0:
            raise RuntimeError("RECENT_TARGET_WINDOW cannot be negative")
        if self.app_env != "production":
            return
        problems = []
        if self.seed_demo:
            problems.append("SEED_DEMO must be false")
        if self.daily_salt in {"development-only-salt", "replace-with-a-long-random-secret-before-production"}:
            problems.append("DAILY_SALT must be a production secret")
        if self.admin_session_secret == "local-admin-session-secret-change-me" or len(self.admin_session_secret) < 32:
            problems.append("ADMIN_SESSION_SECRET must be a production secret")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE must be true")
        if (
            self.admin_password == "replace-with-a-long-random-password"
            or len(self.admin_password) < 16
        ):
            problems.append("ADMIN_PASSWORD must be a production secret of at least 16 characters")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


settings = Settings()
