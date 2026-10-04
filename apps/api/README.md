# apps/api

Deployable unit for the Cairn backend. [`Dockerfile`](Dockerfile) builds **one image**
(build context: repository root) that runs as:

| Process | Command |
|---|---|
| API | `uvicorn cairn.api.main:app --host 0.0.0.0 --port 8000` (default) |
| Temporal worker | `python -m cairn.workflows.worker` |
| Migrations | `sh -c "alembic upgrade head && python -m cairn.context.bootstrap"` |

The application code lives in [`/cairn`](../../cairn). Optional extras can be added at
build time, for example `--build-arg CAIRN_EXTRAS=nemo` for NeMo Guardrails.
