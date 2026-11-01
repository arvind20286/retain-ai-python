import os
from pathlib import Path
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Database settings (Postgres via asyncpg or SQLite fallback)
    db_host: str = Field(default="", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="", alias="DB_NAME")
    db_username: str = Field(default="", alias="DB_USERNAME")
    db_password: str = Field(default="", alias="DB_PASSWORD")
    database_url: str = Field(default="", alias="DATABASE_URL")

    # Notion settings
    notion_api_token: str = Field(default="", alias="NOTION_API_TOKEN")
    notion_datasource_id: str = Field(default="", alias="NOTION_DATASOURCE_ID")

    # Gemini settings
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    model_name: str = Field(default="gemini-3.8-live", alias="MODEL_NAME")
    text_model_name: str = Field(default="gemini-3.5-flash", alias="TEXT_MODEL_NAME")
    gemini_system_prompt: str = Field(default="", alias="GEMINI_SYSTEM_PROMPT")

    # OpenRouter settings
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_model: str = Field(default="deepseek/deepseek-v4.1-flash-1017", alias="OPENROUTER_MODEL")
    openrouter_base_url: str = Field(default="https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")

    # Server settings
    host: str = Field(default="0.0.0.0", validation_alias=AliasChoices("HOST", "SERVER_HOST"))
    port: int = Field(default=8080, validation_alias=AliasChoices("PORT", "SERVER_PORT"))

    def get_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        if self.db_host and self.db_name and self.db_username:
            pwd = f":{self.db_password}" if self.db_password else ""
            return f"postgresql+asyncpg://{self.db_username}{pwd}@{self.db_host}:{self.db_port}/{self.db_name}"
        # Local SQLite fallback for zero-friction local development
        db_path = BASE_DIR / "retain_ai.db"
        return f"sqlite+aiosqlite:///{db_path}"

    def get_text_model_name(self) -> str:
        if self.text_model_name:
            return self.text_model_name
        if "live" in self.model_name.lower():
            return "gemini-3.5-flash"
        return self.model_name

    def get_live_model_name(self) -> str:
        if "live" in self.model_name.lower() or "flash" in self.model_name.lower():
            return self.model_name
        return "gemini-3.8-live"

    def get_system_prompt(self) -> str:
        # If explicitly passed as path or text
        if self.gemini_system_prompt:
            p = Path(self.gemini_system_prompt)
            if p.is_file():
                return p.read_text(encoding="utf-8")
            if (BASE_DIR / self.gemini_system_prompt).is_file():
                return (BASE_DIR / self.gemini_system_prompt).read_text(encoding="utf-8")
            return self.gemini_system_prompt

        # Check default prompt paths
        candidates = [
            BASE_DIR / "retain_ai" / "prompts" / "voice-agent-prompt.txt",
            BASE_DIR / "src" / "main" / "resources" / "prompts" / "voice-agent-prompt.txt",
        ]
        for c in candidates:
            if c.is_file():
                return c.read_text(encoding="utf-8")

        return (
            "You are a voice-based study partner helping a software engineer retain what they've read. "
            "Ask the provided question conversationally, wait for their spoken answer, and relay the feedback warmly."
        )

settings = Settings()

