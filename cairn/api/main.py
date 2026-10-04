"""ASGI entrypoint: ``uvicorn cairn.api.main:app``."""

from cairn.api.app import create_app

app = create_app()
