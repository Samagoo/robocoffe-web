"""Settings read from environment variables (.env)."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_version: str = "0.4.0-phase4"
    database_url: str = "postgresql+psycopg://robocoffee:robocoffee@localhost:5432/robocoffee"

    # Products, tables and provisional order statuses (no migration needed to change them)
    order_config_file: str = str(Path(__file__).with_name("order_config.json"))

    # Robot subsystem: main_real.py (or servidor_simulado.py) listening on TCP
    robot_host: str = "host.docker.internal"
    robot_port: int = 9000
    robot_enabled: bool = True
    # Folder that contains the robot team's robocoffe_cliente.py (mounted read-only from robot/cliente)
    robot_client_dir: str = "/code/robot_cliente"
    # Ask ESTADO every N s while connected, for a live pose (LATIDO has no pose). 0 = off
    robot_poll_s: float = 2.0


settings = Settings()
