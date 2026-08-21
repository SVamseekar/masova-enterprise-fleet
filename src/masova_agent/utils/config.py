"""
Configuration management for MaSoVa Agent
"""
import os
from typing import Optional
from dataclasses import dataclass
from dotenv import load_dotenv

from ..exceptions import ConfigurationError


@dataclass
class AgentConfig:
    """Agent configuration"""
    name: str = "MaSoVa_Intelligence"
    # Model id is env-driven (LLM_MODEL) so the service stays provider-agnostic.
    # Public docs still describe Gemini / Google ADK.
    model: str = "gemini-2.5-flash"
    app_name: str = "masova_support_agent"
    max_retries: int = 3
    timeout: float = 30.0


@dataclass
class APIConfig:
    """API configuration"""
    google_api_key: str  # resolved from LLM_API_KEY or GOOGLE_API_KEY
    use_vertex_ai: bool = False
    location_api_url: str = "http://ip-api.com/json/"
    location_timeout: float = 5.0


@dataclass
class CacheConfig:
    """Cache configuration"""
    enabled: bool = True
    ttl_seconds: int = 3600  # 1 hour
    max_size: int = 1000


@dataclass
class LoggingConfig:
    """Logging configuration"""
    level: str = "INFO"
    format: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    file: Optional[str] = None


class Config:
    """Main configuration class"""

    def __init__(self, env_file: Optional[str] = None):
        """
        Initialize configuration

        Args:
            env_file: Path to .env file (default: auto-detect)
        """
        # Load environment variables (override=True ensures .env values win
        # even if the var was already set as empty in the process environment)
        if env_file:
            load_dotenv(env_file, override=True)
        else:
            load_dotenv(override=True)

        # Initialize sub-configs
        self.agent = AgentConfig(
            model=os.getenv("LLM_MODEL", os.getenv("GOOGLE_MODEL", "gemini-2.5-flash")),
        )
        self.api = self._load_api_config()
        self.cache = CacheConfig()
        self.logging = LoggingConfig(
            level=os.getenv("LOG_LEVEL", "INFO"),
            file=os.getenv("LOG_FILE")
        )

        # Agent infrastructure config
        self.backend_url: str = os.getenv("BACKEND_URL", "http://192.168.50.88:8080")
        self.agent_token: str = os.getenv("AGENT_TOKEN", "")
        self.google_api_key: str = self.api.google_api_key
        self.llm_api_key: str = self.api.google_api_key
        self.llm_model: str = self.agent.model
        self.rabbitmq_url: str = os.getenv("RABBITMQ_URL", "amqp://guest:guest@192.168.50.88:5672/")

    def _load_api_config(self) -> APIConfig:
        """Load API configuration from environment.

        Prefer LLM_API_KEY (provider-agnostic), fall back to GOOGLE_API_KEY
        for existing deployments. Public documentation still refers to Gemini.
        """
        api_key = os.getenv("LLM_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ConfigurationError(
                "LLM_API_KEY or GOOGLE_API_KEY not found in environment. "
                "Please set it in your .env file."
            )

        use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "0") == "1"

        return APIConfig(
            google_api_key=api_key,
            use_vertex_ai=use_vertex,
            location_api_url=os.getenv(
                "LOCATION_API_URL",
                "http://ip-api.com/json/"
            ),
            location_timeout=float(os.getenv("LOCATION_TIMEOUT", "5.0"))
        )

    @classmethod
    def from_env(cls, env_file: Optional[str] = None) -> "Config":
        """Create config from environment file"""
        return cls(env_file)


# Global config instance
_config: Optional[Config] = None


def get_config() -> Config:
    """Get global configuration instance"""
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config(env_file: Optional[str] = None) -> Config:
    """Reload configuration"""
    global _config
    _config = Config(env_file)
    return _config
