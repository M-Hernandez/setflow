from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://setflow:setflow@localhost:5432/setflow"
    anthropic_api_key: str = ""
    voyage_api_key: str = ""
    spotify_client_id: str = ""
    spotify_client_secret: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
