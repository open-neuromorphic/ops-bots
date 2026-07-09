#!/usr/bin/env python3
import os
import sys
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import config
from utils import google_api_utils

logger = logging.getLogger(__name__)

def run_auth():
    logger.info("Initializing Google Calendar API authentication...")
    try:
        creds = google_api_utils.get_credentials(config.CALENDAR_TOKEN_FILE, config.CALENDAR_SCOPES)
        if creds and creds.valid:
            logger.info(f"✅ Success! Calendar token saved to '{config.CALENDAR_TOKEN_FILE}'")
        else:
            logger.error("❌ Authentication failed or was aborted.")
    except Exception as e:
        logger.exception(f"An unexpected error occurred during auth: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    run_auth()