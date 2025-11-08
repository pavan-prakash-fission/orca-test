"""
This module defines the application's configuration settings.

It uses pydantic-settings to load configuration from environment
variables and a .env file.
"""

import os
from typing import List
from pydantic_settings import BaseSettings


from pydantic_settings import BaseSettings, SettingsConfigDict

# Define the base directory of the project
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


class Settings(BaseSettings):
    """
    Manages application settings loaded from a .env file and environment variables.

    # --- App Core Settings ---
        Application configuration settings.
        Loaded from environment variables or a .env file.

        app_name: Name of the application.
        debug: Enable or disable debug mode.
        environment: Application environment (development, production, etc.).
        default_source: Default source for the application (e.g., prod).
        db_url: Database connection URL.
        cors_origins: Comma-separated list of allowed CORS origins.
        cors_allow_credentials: Whether to allow credentials in CORS.
        cors_allow_methods: List of allowed HTTP methods for CORS.
        cors_allow_headers: List of allowed HTTP headers for CORS.

    """
    app_name: str = "FastAPI App"
    debug: bool = True
    environment: str = "development"
    default_source: str

    # --- Database Settings ---
    db_url: str

    # --- CORS Settings ---
    cors_origins: str
    cors_allow_credentials: bool = True
    cors_allow_methods: List[str] = ["*"]  # For development only
    cors_allow_headers: List[str] = ["*"]  # For development only

    def get_cors_origins(self) -> List[str]:
        """Parses the comma-separated cors_origins string into a list."""
        return [
            origin.strip() for origin in self.cors_origins.split(",") if origin.strip()
        ]

    # --- Pydantic Model Configuration ---
    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"), env_file_encoding="utf-8"
    )

    # --- AWS Credentials ---
    aws_access_key_id: str
    aws_secret_access_key: str
    region: str
    bucket: str

    # --- Celery Settings ---
    celery_backend: str
    celery_broker: str

    # --- File Path Settings ---
    s3_local_path: str
    prod_zip_name: str
    preprod_zip_name: str
    docs_zip_name: str

    # --- Watermark Setting ---
    is_watermark_enabled: bool = False

    # --- SMTP Settings ---
    smtp_sender: str
    smtp_app_password: str

    # --- Lustre Settings ---
    lustre_base_path: str  
    lustre_user: str
    lustre_user_password: str

    # --- LDAP Settings ---
    ldap_server_uri: str
    ldap_org_unit: str
    ldap_search_attribute: str
    ldap_server_available: bool
    ldap_group_filter: bool
    ldap_allowed_groups: str


# Create a single instance of the settings to be used throughout the application
settings = Settings()
