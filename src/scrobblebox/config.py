from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


load_dotenv()


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    lastfm_api_key: str = Field(default="", alias="LASTFM_API_KEY")
    lastfm_api_secret: str = Field(default="", alias="LASTFM_API_SECRET")
    lastfm_session_key: str = Field(default="", alias="LASTFM_SESSION_KEY")
    lastfm_username: str = Field(default="", alias="LASTFM_USERNAME")

    discogs_token: str = Field(default="", alias="DISCOGS_TOKEN")
    discogs_username: str = Field(default="", alias="DISCOGS_USERNAME")
    discogs_collection_folder_id: int = Field(default=0, alias="DISCOGS_COLLECTION_FOLDER_ID")

    audio_input_device: str = Field(default="", alias="AUDIO_INPUT_DEVICE")
    audio_sample_rate: int = Field(default=44100, alias="AUDIO_SAMPLE_RATE")
    audio_channels: int = Field(default=2, alias="AUDIO_CHANNELS")
    audio_block_seconds: float = Field(default=0.5, alias="AUDIO_BLOCK_SECONDS")
    shazam_clip_seconds: int = Field(default=12, alias="SHAZAM_CLIP_SECONDS")
    silence_threshold: float = Field(default=0.01, alias="SILENCE_THRESHOLD")
    silence_tolerance_seconds: int = Field(default=5, alias="SILENCE_TOLERANCE_SECONDS")
    recognition_cooldown_seconds: int = Field(default=20, alias="RECOGNITION_COOLDOWN_SECONDS")
    discogs_match_threshold: int = Field(default=160, alias="DISCOGS_MATCH_THRESHOLD")
    discogs_candidate_limit: int = Field(default=8, alias="DISCOGS_CANDIDATE_LIMIT")
    clip_storage_directory: Path = Field(default=Path("runtime/clips"), alias="CLIP_STORAGE_DIRECTORY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    lyrics_host: str = Field(default="127.0.0.1", alias="LYRICS_HOST")
    lyrics_port: int = Field(default=8765, alias="LYRICS_PORT")
    lyrics_directory: Path = Field(default=Path("lyrics"), alias="LYRICS_DIRECTORY")

    kasa_device_alias: str = Field(default="Oscilloscope", alias="KASA_DEVICE_ALIAS")
    oscilloscope_idle_minutes: int = Field(default=15, alias="OSCILLOSCOPE_IDLE_MINUTES")


settings = Settings()
