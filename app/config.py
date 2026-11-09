import os
from dataclasses import dataclass
from pathlib import Path


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value


PROJECT_ROOT = Path(__file__).resolve().parents[1]
_load_env_file(PROJECT_ROOT / "dev.env")


@dataclass(frozen=True)
class Settings:
    mysql_host: str = os.getenv("mysql_host", "localhost")
    mysql_username: str = os.getenv("mysql_username", "root")
    mysql_pass: str = os.getenv("mysql_pass", "")
    mysql_port: int = int(os.getenv("mysql_port", "3306"))
    mysql_db: str = os.getenv("mysql_db", "conquered")
    jwt_secret: str = os.getenv("jwt_secret", "change-me-in-prod")
    jwt_algorithm: str = "HS256"
    token_exp_hours: int = int(os.getenv("token_exp_hours", "720"))
    api_title: str = "Conquered API"
    cors_origins: str = os.getenv("cors_origins", "*")


settings = Settings()
