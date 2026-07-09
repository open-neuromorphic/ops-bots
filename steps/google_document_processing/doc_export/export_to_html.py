import os
import logging
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import config
from utils import google_api_utils

logger = logging.getLogger(__name__)

def export_doc_as_html(doc_id: str = None):
    if not doc_id:
        doc_id = config.DOCUMENT_ID

    os.makedirs(config.FINAL_OUTPUT_DIR, exist_ok=True)
    output_filepath = os.path.join(config.FINAL_OUTPUT_DIR, f"document_export_{doc_id}.html")

    logger.info(f"Attempting to export Google Doc ID: {doc_id}")

    creds = google_api_utils.get_credentials(config.DRIVE_TOKEN_FILE, config.DRIVE_SCOPES)
    drive_service = build("drive", "v3", credentials=creds)

    file_metadata = drive_service.files().get(fileId=doc_id, fields='name').execute()
    doc_title = file_metadata.get('name', 'Untitled Document')

    request = drive_service.files().export_media(
        fileId=doc_id, mimeType='text/html'
    )
    response_content = request.execute()

    if not response_content:
        raise ValueError("The Google API returned empty content for the export request.")

    with open(output_filepath, 'wb') as f:
        f.write(response_content)

    logger.info(f"Successfully exported '{doc_title}' ({doc_id}) to '{output_filepath}'")
    return output_filepath, doc_title

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        export_doc_as_html()
    except Exception as e:
        logger.exception(f"Error during standard execution: {e}")