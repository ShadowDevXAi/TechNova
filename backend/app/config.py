from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    mongodb_uri: str = "mongodb://localhost:27017/technova"
    database_name: str = "technova"
    jwt_secret: str = Field(min_length=32)
    jwt_expire_minutes: int = 720
    frontend_origins: str = "http://localhost:5173,http://localhost:8080"
    public_app_url: str = "http://localhost:8080"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    bootstrap_founder_name: str = "Club Founder"
    bootstrap_founder_email: str = "founder@example.com"
    bootstrap_founder_password: str = Field(min_length=12)
    def origins(self) -> list[str]:
        return [x.strip() for x in self.frontend_origins.split(",") if x.strip()]

settings = Settings()
