"""
Supabase Client Initialization
-----------------------------

This module is responsible for creating and sharing a single instance of
the Supabase client throughout the application.

Key concepts explained in plain language:

* **Environment variables** – The Supabase URL and API key are read
  from environment variables (often stored in a `.env` file when
  developing locally).  If these variables are missing or invalid the
  client cannot connect.
* **Singleton pattern** – The :class:`SupabaseConnection` class is
  written as a singleton.  This means there is only ever one instance
  of the client; subsequent attempts to create the class return the
  same object.  This design ensures a single, shared connection pool.
* **CI awareness** – When running in continuous integration (CI)
  environments, the module relaxes some checks and attempts to use
  provided credentials if they are present.

Use the :func:`get_supabase_client` function provided at the bottom of
this file to obtain the client in your code.  It will either return a
working client or ``None`` if the client could not be initialized.  All
error messages are logged for easier debugging.
"""

from supabase import create_client, Client
import os
import sys
import logging
from dotenv import load_dotenv
from typing import Optional

logger = logging.getLogger(__name__)


class SupabaseConnection:
    """Singleton wrapper around the Supabase client.

    Creating multiple instances of this class will return the same
    underlying object, ensuring that only one Supabase client is ever
    created.  The client is lazily initialized the first time it is
    needed.
    """
    _instance: Optional['SupabaseConnection'] = None
    _client: Optional[Client] = None

    def __new__(cls) -> 'SupabaseConnection':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is None:
            self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize the Supabase client with environment aware logic."""
        # Load environment variables from a .env file if present (useful for local development)
        load_dotenv()

        SUPABASE_URL = os.getenv("SUPABASE_URL")
        SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        IS_CI = os.getenv("CI") == 'true' or os.getenv("GITHUB_ACTIONS") == 'true'

        # Log whether credentials were found for easier troubleshooting
        logger.debug(f"SUPABASE_URL found: {'Yes' if SUPABASE_URL else 'No'}")
        logger.debug(f"SUPABASE_KEY found: {'Yes' if SUPABASE_KEY else 'No'}")
        logger.debug(f"CI environment: {IS_CI}")

        # Clean up and validate the URL
        if SUPABASE_URL:
            SUPABASE_URL = SUPABASE_URL.strip().strip('"\'')
            if not SUPABASE_URL.startswith(('http://', 'https://')):
                logger.error(f"Invalid SUPABASE_URL format: {SUPABASE_URL}")
                SUPABASE_URL = None

        # Clean up and validate the API key
        if SUPABASE_KEY:
            SUPABASE_KEY = SUPABASE_KEY.strip().strip('"\'')
            if not SUPABASE_KEY.strip():
                logger.error("SUPABASE_KEY appears to be empty")
                SUPABASE_KEY = None

        # Attempt to create the client depending on context
        if SUPABASE_URL and SUPABASE_KEY and not IS_CI:
            try:
                self._client = create_client(SUPABASE_URL, SUPABASE_KEY)
                logger.info("Supabase client initialized successfully")
            except Exception as e:
                logger.warning(f"Failed to initialize Supabase client: {e}")
                logger.debug(f"URL: {SUPABASE_URL[:50]}...")
                self._client = None
        elif IS_CI and SUPABASE_URL and SUPABASE_KEY and not SUPABASE_KEY.startswith('test-'):
            try:
                self._client = create_client(SUPABASE_URL, SUPABASE_KEY)
                logger.info("Supabase client initialized in CI environment")
            except Exception as e:
                logger.warning(f"Failed to initialize Supabase client in CI: {e}")
                logger.debug(f"URL: {SUPABASE_URL[:50]}...")
                self._client = None
        elif not IS_CI and (not SUPABASE_URL or not SUPABASE_KEY):
            # Credentials are missing; log errors and exit if running outside tests/CI
            logger.error("SUPABASE_URL and/or SUPABASE_KEY environment variables are not set or invalid.")
            logger.error("Please check your .env file or environment variable configuration.")
            is_testing = 'pytest' in sys.modules or os.getenv('TESTING') == 'true'
            is_exit_mocked = hasattr(sys.exit, '_mock_name') or str(type(sys.exit)).find('Mock') != -1
            if not IS_CI and (not is_testing or is_exit_mocked):
                sys.exit(1)
        else:
            logger.warning("Supabase credentials not available or running in CI mode. Database access disabled.")

        # Additional validation for Docker environments – only warn, don't exit
        if self._client is None and not IS_CI:
            is_testing = 'pytest' in sys.modules or os.getenv('TESTING') == 'true'
            if not is_testing:
                logger.error("Could not initialize Supabase client. Please verify:")
                logger.error("1. Your .env file contains valid SUPABASE_URL and SUPABASE_KEY")
                logger.error("2. The URL starts with 'https://' and is properly formatted")
                logger.error("3. The API key is not empty or malformed")
                logger.error("4. If running in Docker, ensure --env-file is used correctly")

    @property
    def client(self) -> Optional[Client]:
        """Return the Supabase client instance if initialized, else None."""
        return self._client

    def is_connected(self) -> bool:
        """Check whether the client is connected (i.e., properly initialized)."""
        return self._client is not None

    def debug_env_vars(self) -> dict:
        """Debug helper that returns the status of environment variables and client.

        Returns a dictionary indicating whether the SUPABASE_URL and
        SUPABASE_KEY environment variables are set, whether the code is
        running in a CI environment, and whether the client is initialized.
        """
        load_dotenv()
        return {
            'SUPABASE_URL_set': bool(os.getenv("SUPABASE_URL")),
            'SUPABASE_KEY_set': bool(os.getenv("SUPABASE_KEY")),
            'CI_mode': os.getenv("CI") == 'true' or os.getenv("GITHUB_ACTIONS") == 'true',
            'client_initialized': self._client is not None
        }


# Convenience function to get the client
def get_supabase_client() -> Optional[Client]:
    """Get the shared Supabase client instance.

    Calling this function returns the same client each time.  If the
    client could not be created (for example, due to missing
    environment variables), it returns ``None``.
    """
    return SupabaseConnection().client