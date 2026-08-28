import sys
from pathlib import Path

from serverless_wsgi import handle_request


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import app


def handler(event, context):
    return handle_request(app, event, context)
