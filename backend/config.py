import os
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        self.project_root = Path(os.getenv("DTCM_PROJECT_ROOT", Path.cwd())).resolve()
        self.backend_host = os.getenv("DTCM_BACKEND_HOST", "0.0.0.0")
        self.backend_port = _int_env("DTCM_BACKEND_PORT", 8001)
        self.cors_origins_raw = os.getenv("DTCM_CORS_ORIGINS", "*")
        self.max_read_bytes = _int_env("DTCM_MAX_READ_BYTES", 1_000_000)
        self.command_timeout_seconds = _int_env("DTCM_COMMAND_TIMEOUT_SECONDS", 60)
        self.allow_source_write = _bool_env("DTCM_ALLOW_SOURCE_WRITE", False)

    @property
    def cors_origins(self) -> list[str]:
        if self.cors_origins_raw == "*":
            return ["*"]
        return [origin.strip() for origin in self.cors_origins_raw.split(",") if origin.strip()]

    @property
    def skills_dir(self) -> Path:
        return self.project_root / "skills"

    @property
    def pipelines_dir(self) -> Path:
        return self.project_root / "pipelines"

    @property
    def output_dir(self) -> Path:
        return self.project_root / "output"

    @property
    def traces_dir(self) -> Path:
        return self.project_root / "traces"

    @property
    def generated_dir(self) -> Path:
        return self.project_root / "generated"

    def ensure_directories(self) -> None:
        for directory in (
            self.skills_dir,
            self.pipelines_dir,
            self.output_dir,
            self.traces_dir,
            self.generated_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
