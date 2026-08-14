from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("STEP_API_KEY", "STEPFUN_API_KEY", "OPENAI_API_KEY"),
    )
    openai_base_url: str = "https://api.stepfun.com/step_plan/v1"
    agentmed_model: str = "step-3.7-flash"
    langfuse_host: str = "http://localhost:3001"
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    database_url: str = "sqlite:///./data/agentmed.db"
    agentmed_data_dir: Path = Path("./data")
    caseloop_eval_token: str = ""
    evaluate_registry_path: str = "workloads/xiaozhi-customer-service/registry.json"
    github_token: str = ""
    require_live: bool = True
    kernel_listen_host: str = "0.0.0.0"
    kernel_api_host: str = "127.0.0.1"
    kernel_api_port: int = 8088
    worker_kernel_url: str = "http://host.docker.internal:8088"
    agentteams_gateway: str = "http://127.0.0.1:18080"
    agentteams_element: str = "http://127.0.0.1:18088"
    agentteams_dashboard: str = "http://127.0.0.1:13000"
    agentteams_workspace: Path = Path.home() / "agentteams-manager"

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key)

    @property
    def kernel_api_url(self) -> str:
        return f"http://{self.kernel_api_host}:{self.kernel_api_port}"


def load_settings() -> Settings:
    return Settings()
