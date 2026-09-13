from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./converge.db"
    app_env: Literal["local", "staging", "production"] = "local"
    deployment_id: str = "converge-local"
    app_version: str = "development"
    cookie_secure: bool = False
    frontend_origin: str = "http://localhost:5173"
    public_base_url: str = "http://localhost:5173"
    daily_salt: str = "development-only-salt"
    recent_target_window: int = 30
    seed_demo: bool = False
    admin_session_secret: str = "local-admin-session-secret-change-me"
    admin_oidc_discovery_url: str = ""
    admin_oidc_client_id: str = ""
    admin_oidc_client_secret: str = ""
    admin_oidc_allowed_subjects: str = ""
    admin_local_login_enabled: bool = False
    operator_job_poll_seconds: float = 2.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def allowed_admin_subjects(self) -> set[str]:
        return {subject.strip() for subject in self.admin_oidc_allowed_subjects.split(",") if subject.strip()}

    @property
    def oidc_configured(self) -> bool:
        return bool(
            self.admin_oidc_discovery_url
            and self.admin_oidc_client_id
            and self.admin_oidc_client_secret
            and self.allowed_admin_subjects
        )

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
        if not self.oidc_configured:
            problems.append("allowlisted administrator OIDC must be configured")
        if self.admin_local_login_enabled:
            problems.append("ADMIN_LOCAL_LOGIN_ENABLED must be false")
        if problems:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


settings = Settings()
