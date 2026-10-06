from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "LimAnalysis API"
    api_prefix: str = "/api/v1"
    cors_origins: str = "http://localhost:8848,http://127.0.0.1:8848"

    meta_sqlite_path: str = ""
    raw_database_url: str = "postgresql+psycopg://lim:lim@127.0.0.1:5432/lim_raw"
    dwh_database_url: str = "postgresql+psycopg://lim:lim@127.0.0.1:5433/lim_dwh"
    defect_database_url: str = "postgresql+psycopg://lim:lim@127.0.0.1:5434/lim_defect"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def sqlite_file(self) -> Path:
        if self.meta_sqlite_path:
            return Path(self.meta_sqlite_path)
        return REPO_ROOT / "data" / "meta" / "lim_meta.sqlite"

    @property
    def meta_database_url(self) -> str:
        path = self.sqlite_file.resolve().as_posix()
        return f"sqlite:///{path}"

    @property
    def raw_csv_dir(self) -> Path:
        path = REPO_ROOT / "data" / "raw"
        path.mkdir(parents=True, exist_ok=True)
        return path


settings = Settings()
