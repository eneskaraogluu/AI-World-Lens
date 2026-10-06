import os
import urllib.parse

from dotenv import load_dotenv


load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


class Settings:
    APP_NAME = os.getenv("APP_NAME", "AI_World_Lens")
    SERVERLESS_MODE = os.getenv("SERVERLESS_MODE", os.getenv("VERCEL", "")).strip().lower() in {
        "1", "true", "yes"
    }

    DB_SERVER = os.getenv("DB_SERVER", r".\SQLEXPRESS")
    DB_DATABASE = os.getenv("DB_DATABASE", "WorldLensDB")
    DB_DRIVER = os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server")

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
    GEMINI_MODEL = os.getenv(
        "GEMINI_ANALYSIS_MODEL",
        os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    ).strip()
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
    PRIMARY_VISION_PROVIDER = os.getenv("PRIMARY_VISION_PROVIDER", "gemini").strip().lower()
    FALLBACK_VISION_PROVIDER = os.getenv("FALLBACK_VISION_PROVIDER", "openai").strip().lower()
    OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4o-mini").strip()
    OPENAI_VISION_DETAIL = os.getenv("OPENAI_VISION_DETAIL", "low").strip().lower()
    OPENAI_VISION_TIMEOUT_SECONDS = max(
        10, _env_int("OPENAI_VISION_TIMEOUT_SECONDS", 60)
    )
    VISION_WORKERS = min(2, max(1, _env_int("VISION_WORKERS", 2)))
    VISION_TEST_SIMULATE_GEMINI_QUOTA = os.getenv(
        "VISION_TEST_SIMULATE_GEMINI_QUOTA", "false"
    ).strip().lower() in {"1", "true", "yes"}
    IMAGE_PROVIDER = os.getenv("IMAGE_PROVIDER", "openai").strip().lower()
    OPENAI_IMAGE_MODEL = os.getenv("OPENAI_IMAGE_MODEL", "gpt-image-2").strip()
    OPENAI_IMAGE_QUALITY = os.getenv("OPENAI_IMAGE_QUALITY", "low").strip()
    OPENAI_IMAGE_SIZE = os.getenv("OPENAI_IMAGE_SIZE", "1024x1024").strip()
    OPENAI_TIMEOUT_SECONDS = max(30, _env_int("OPENAI_TIMEOUT_SECONDS", 180))
    POLLINATIONS_API_KEY = os.getenv("POLLINATIONS_API_KEY", "").strip()
    POLLINATIONS_MODEL = os.getenv("POLLINATIONS_MODEL", "flux").strip()

    # Two workers keep the presentation responsive without sending five image
    # and vision requests in the same burst, which triggers provider rate limits.
    QUEUE_WORKERS = min(2, max(1, _env_int("QUEUE_WORKERS", 2)))
    RUN_ITERATIONS = min(10, max(1, _env_int("RUN_ITERATIONS", 10)))
    POLLINATIONS_MIN_INTERVAL_SECONDS = max(
        0.0, _env_float("POLLINATIONS_MIN_INTERVAL_SECONDS", 8.0)
    )
    POLLINATIONS_TIMEOUT_SECONDS = max(
        10, _env_int("POLLINATIONS_TIMEOUT_SECONDS", 60)
    )

    def __init__(self) -> None:
        if self.IMAGE_PROVIDER not in {"openai", "pollinations"}:
            raise ValueError("Unsupported IMAGE_PROVIDER. Use 'openai' or 'pollinations'.")
        if self.PRIMARY_VISION_PROVIDER != "gemini":
            raise ValueError("PRIMARY_VISION_PROVIDER must be 'gemini'.")
        if self.FALLBACK_VISION_PROVIDER not in {"openai", "none", "disabled"}:
            raise ValueError("FALLBACK_VISION_PROVIDER must be 'openai' or 'none'.")
        if self.OPENAI_VISION_DETAIL not in {"low", "high", "auto"}:
            raise ValueError("OPENAI_VISION_DETAIL must be 'low', 'high', or 'auto'.")
        if self.OPENAI_IMAGE_SIZE not in {"1024x1024", "1536x1024", "1024x1536", "auto"}:
            raise ValueError("OPENAI_IMAGE_SIZE must be a supported GPT Image size.")
        if self.OPENAI_IMAGE_QUALITY not in {"low", "medium", "high", "auto"}:
            raise ValueError("OPENAI_IMAGE_QUALITY must be low, medium, high, or auto.")

    @property
    def DATABASE_URL(self) -> str:
        explicit_url = os.getenv("DATABASE_URL", os.getenv("POSTGRES_URL", "")).strip()
        if explicit_url:
            if explicit_url.startswith("postgres://"):
                return "postgresql+psycopg://" + explicit_url[len("postgres://"):]
            if explicit_url.startswith("postgresql://"):
                return "postgresql+psycopg://" + explicit_url[len("postgresql://"):]
            return explicit_url

        conn_str = (
            f"DRIVER={{{self.DB_DRIVER}}};"
            f"SERVER={self.DB_SERVER};"
            f"DATABASE={self.DB_DATABASE};"
            "Trusted_Connection=yes;"
        )
        return f"mssql+pyodbc:///?odbc_connect={urllib.parse.quote_plus(conn_str)}"


settings = Settings()
