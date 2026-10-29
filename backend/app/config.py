from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    mongodb_uri: str = "mongodb+srv://bak072007_db_user:technova2007@technova.oljkj37.mongodb.net/"
    database_name: str = "technova"
    jwt_secret: str = Field(min_length=32)
    jwt_expire_minutes: int = 720
    frontend_origins: str = "https://technova-1-qx44.onrender.com/"
    public_app_url: str = "https://technova-1-qx44.onrender.com/"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_use_tls: bool = True
    bootstrap_founder_name: str = ""
    bootstrap_founder_email: str = ""
    bootstrap_founder_password: str = Field(min_length=12)
    def origins(self) -> list[str]:
        return [x.strip() for x in self.frontend_origins.split(",") if x.strip()]

settings = Settings()
