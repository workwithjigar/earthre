"""AWS Lambda entry point. Mangum translates Lambda Function URL / API Gateway
events into ASGI requests for the FastAPI app."""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off")
