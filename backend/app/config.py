import os

# sqlite for local dev; a Postgres URL (e.g. Neon free tier) in the cloud:
#   postgresql+psycopg2://user:pass@host/db?sslmode=require
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./local.db")


# Comma-separated list of allowed browser origins, "*" for any.
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

# Lambda's synchronous invoke payload limit is 6 MB (and base64 inflates multipart bodies ~33%).
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(4 * 1024 * 1024)))

SLA_TARGET = float(os.getenv("SLA_TARGET", "99.9"))
SLOW_THRESHOLD_MS = float(os.getenv("SLOW_THRESHOLD_MS", "1000"))
