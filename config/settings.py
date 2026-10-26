from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass, field
from dotenv import load_dotenv

# Base paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"

# Load environment variables
load_dotenv(dotenv_path=ENV_PATH)


@dataclass
class Settings:
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "")
    )
    mock_app_url: str = field(
        default_factory=lambda: os.getenv("MOCK_APP_URL", "http://localhost:5001")
    )
    browser_headless: bool = field(
        default_factory=lambda: os.getenv("BROWSER_HEADLESS", "false").lower()
        in ("1", "true", "yes")
    )
    max_retries: int = field(
        default_factory=lambda: int(os.getenv("MAX_RETRIES", "2"))
    )
    screenshot_dir: Path = field(
        default_factory=lambda: PROJECT_ROOT / os.getenv("SCREENSHOT_DIR", "screenshots")
    )
    db_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / os.getenv("DB_PATH", "autoworker.db")
    )
    log_file: Path = field(
        default_factory=lambda: PROJECT_ROOT / os.getenv("LOG_FILE", "agent_run.json")
    )
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    )

    def __post_init__(self):
        # Ensure directories exist
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        if self.db_path.parent:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.log_file.parent:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)


# Default global settings instance
settings = Settings()

# Direct module-level exports as specified
GEMINI_API_KEY = settings.gemini_api_key
MOCK_APP_URL = settings.mock_app_url
BROWSER_HEADLESS = settings.browser_headless
MAX_RETRIES = settings.max_retries
SCREENSHOT_DIR = str(settings.screenshot_dir)
DB_PATH = str(settings.db_path)
LOG_FILE = str(settings.log_file)
GEMINI_MODEL = settings.gemini_model
