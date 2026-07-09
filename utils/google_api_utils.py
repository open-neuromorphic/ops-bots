"""
Utility functions for handling Google API authentication and credential management.
"""

import os
from typing import List

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

import config


def get_credentials(token_file: str, scopes: List[str]) -> Credentials:
    """
    Gets valid user credentials from storage or grants new ones via OAuth flow.

    Args:
        token_file (str): The path to the token file (e.g., 'token.json').
        scopes (List[str]): A list of API scopes to request.

    Returns:
        Credentials: A valid Google OAuth2 credentials object.
    """
    creds = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(config.CREDENTIALS_FILE, scopes)
            creds = flow.run_local_server(port=0)

        with open(token_file, "w") as token:
            token.write(creds.to_json())

    return creds