from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import EmailStr, Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    mongodb_uri: str = Field(min_length=1)
    database_name: str = "technova"
    jwt_secret: str = Field(min_length=32)
    jwt_expire_minutes: int = 720
    frontend_origins: str = "https://technova-1-qx44.onrender.com"
    public_app_url: str = "https://technova-1-qx44.onrender.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    bootstrap_founder_name: str = Field(min_length=2)
    bootstrap_founder_email: EmailStr
    bootstrap_founder_password: str = Field(min_length=12)
    def origins(self) -> list[str]:
        return list(dict.fromkeys(
            origin.strip().rstrip("/")
            for origin in self.frontend_origins.split(",")
            if origin.strip()
        ))

settings = Settings()
