"""Settings read from environment variables (.env)."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_version: str = "0.1.0-phase1"
    database_url: str = "postgresql+psycopg://robocoffee:robocoffee@localhost:5432/robocoffee"

    # Robot subsystem: main_real.py (or servidor_simulado.py) listening on TCP
    robot_host: str = "host.docker.internal"
    robot_port: int = 9000


settings = Settings()
