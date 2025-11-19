"""
Unified dictionary interface that automatically selects PostgreSQL backend
based on environment configuration.
"""

import os
import logging
from typing import Union
from libs.pg_dictionary import PostgresDictionary

logger = logging.getLogger(__name__)

# Alias for backward compatibility
Dictionary = PostgresDictionary(os.getenv("POSTGRES_CONNECTION"))