from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    azure_read_endpoint: str | None
    azure_read_key: str | None
    azure_read_model: str = "prebuilt-read"
    azure_ocr_max_workers: int = 6
    azure_ocr_max_retries: int = 3
    azure_read_verify_ssl: bool = True
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-2.5-flash"
    extraction_window_size: int = 6
    extraction_window_overlap: int = 1
    extraction_max_workers: int = 4


def _int_env(name: str, default: int) -> int:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        return default
    return max(1, value)


def _bool_env(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.lower().strip() not in {"0", "false", "no", "off"}


def get_settings() -> Settings:
    azure_disable_ssl_verify = _bool_env("AZURE_DISABLE_SSL_VERIFY", False)
    return Settings(
        azure_read_endpoint=os.getenv("AZURE_READ_SERVICE_ENDPOINT")
        or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"),
        azure_read_key=os.getenv("AZURE_READ_SERVICE_KEY")
        or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY"),
        azure_read_model=os.getenv("AZURE_READ_MODEL", "prebuilt-read"),
        azure_ocr_max_workers=_int_env("AZURE_OCR_MAX_WORKERS", 6),
        azure_ocr_max_retries=_int_env("AZURE_OCR_MAX_RETRIES", 3),
        azure_read_verify_ssl=not azure_disable_ssl_verify
        and _bool_env("AZURE_READ_VERIFY_SSL", True),
        gemini_api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
        extraction_window_size=_int_env("EXTRACTION_WINDOW_SIZE", 6),
        extraction_window_overlap=_int_env("EXTRACTION_WINDOW_OVERLAP", 1),
        extraction_max_workers=_int_env("EXTRACTION_MAX_WORKERS", 4),
    )
