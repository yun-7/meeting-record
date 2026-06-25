import os

# Must be set before app.py is imported so SITE_PASSWORD and GCS_BUCKET
# are picked up at module load time.
os.environ["SITE_PASSWORD"] = "testpass"
os.environ.pop("GCS_BUCKET", None)
