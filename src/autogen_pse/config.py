"""Centralized configuration via pydantic-settings."""

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT = Path(__file__).parent.parent.parent

# 将 .env 导出到 os.environ（override=False：真实环境变量优先）。
# pydantic-settings 只把 .env 读进 Settings 模型、不写 os.environ，而 tools.py
# 的 RAG 开关（RAG_STORE / RAG_SOURCE_DIRS / RAG_EXCLUDE_PATTERNS 等）走
# os.getenv。缺此桥接时 .env 里配置的隐私过滤会静默失效——
# 2026-10-24 隐私审计发现并修复（full 域成默认后该过滤是隐私红线，必须真生效）。
load_dotenv(ROOT / ".env", override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", case_sensitive=False, extra="ignore"
    )

    # LLM
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL: str = ""

    # Model streaming (disable for providers with unstable streaming like Agnes free tier)
    PSE_MODEL_STREAM: bool = True

    # External project paths (for portfolio-review)
    ASSET_LENS_DIR: str = ""
    MONEY_CSV_DIR: str = ""

    # Knowledge base (langchain-llm-toolkit RAG, optional)
    KNOWLEDGE_BASE_PATH: str = ""

    # Trace output
    PSE_TRACE_DIR: str = "outputs/traces"

    # Issue detection thresholds (must be set in .env)
    PSE_LONG_LOSS_DAYS: int = 0
    PSE_LOW_EFF_DAYS: int = 0
    PSE_LOW_EFF_MAX_RETURN: float = 0.0
    PSE_LOW_EFF_MIN_AMOUNT: int = 0
    PSE_HIGH_VOL_MIN_RETURN: float = 0.0
    PSE_HIGH_VOL_MAX_DAYS: int = 0
    PSE_HIGH_VOL_MIN_AMOUNT: int = 0
    PSE_LARGE_POS_TYPES: str = ""
    PSE_LARGE_POS_MIN_AMOUNT: int = 0
    PSE_LARGE_POS_MAX_RETURN: float = 0.0

    # Current loss detection (any holding period)
    PSE_CUR_LOSS_THRESHOLD: float = -5.0
    PSE_CUR_LOSS_MIN_AMOUNT: int = 3000

    # Market indices (comma-separated, must be set in .env)
    MARKET_INDICES: str = ""

    # Property column mapping (CSV header names, keep in .env for privacy)
    PROP_CORE_VALUE: str = ""
    PROP_CORE_ESTIMATE: str = ""
    PROP_CORE_DIFF: str = ""
    PROP_CORE_UNITS: str = ""
    PROP_CORE_PRICE: str = ""
    PROP_CORE_LISTING: str = ""
    PROP_DISTRICTS: str = ""  # comma-separated
    PROP_OLD_VALUE: str = ""  # comma-separated

    # Web dashboard CORS
    CORS_ORIGINS: str = "http://localhost:5173"

    # Web dashboard auth token (empty = no auth; bind to 127.0.0.1 only)
    WEB_AUTH_TOKEN: str = ""

    @property
    def trace_dir(self) -> Path:
        return ROOT / self.PSE_TRACE_DIR

    @property
    def market_indices_list(self) -> list[str]:
        return [x.strip() for x in self.MARKET_INDICES.split(",")]

    @property
    def large_pos_types_list(self) -> list[str]:
        return [x.strip() for x in self.PSE_LARGE_POS_TYPES.split(",")]

    @property
    def has_knowledge_base(self) -> bool:
        return (
            bool(self.KNOWLEDGE_BASE_PATH)
            and (ROOT / self.KNOWLEDGE_BASE_PATH).exists()
        )

    @property
    def resolved_asset_lens_dir(self) -> Path | None:
        if not self.ASSET_LENS_DIR:
            return None
        p = Path(self.ASSET_LENS_DIR)
        return p if p.is_absolute() else (ROOT / p).resolve()

    @property
    def resolved_money_csv_dir(self) -> Path | None:
        if not self.MONEY_CSV_DIR:
            return None
        p = Path(self.MONEY_CSV_DIR)
        return p if p.is_absolute() else (ROOT / p).resolve()


settings = Settings()
