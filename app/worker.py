import logging
from typing import Any
from uuid import UUID, uuid4

from redis.exceptions import ResponseError

from app.db.models import Job
from app.db.session import SessionLocal
from app.queue import JOB_STREAM
from app.redis_client import redis_client

CONSUMER_GROUP = "taskflow-workers"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def ensure_consumer_group() -> None:
    """Create the shared worker group, or keep using it if it exists."""
    try:
        redis_client.xgroup_create(
            name=JOB_STREAM,
            groupname=CONSUMER_GROUP,
            id="0",
            mkstream=True,
        )
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


def process_job(job_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Run the handler for one job and return its result."""
    if job_type != "csv_summary":
        raise ValueError(f"Unsupported job type: {job_type}")

    rows = payload.get("rows")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("csv_summary requires payload.rows to be a list of row objects")

    columns = sorted({str(column) for row in rows for column in row.keys()})
    return {
        "row_count": len(rows),
        "columns": columns,
    }


def handle_message(message_id: str, fields: dict[str, str]) -> None:
    """Load a job, process it, save its outcome, then acknowledge the message."""
    job_id_text = fields.get("job_id")
    if not job_id_text:
        logger.error("Stream message %s has no job_id", message_id)
        redis_client.xack(JOB_STREAM, CONSUMER_GROUP, message_id)
        return

    try:
        job_id = UUID(job_id_text)
    except ValueError:
        logger.error("Stream message %s has an invalid job_id", message_id)
        redis_client.xack(JOB_STREAM, CONSUMER_GROUP, message_id)
        return

    with SessionLocal() as db:
        job = db.get(Job, job_id)

        if job is None:
            logger.error("Job %s is missing from PostgreSQL", job_id)
            redis_client.xack(JOB_STREAM, CONSUMER_GROUP, message_id)
            return

        if job.status != "queued":
            # Ignore duplicate or already-finished messages.
            redis_client.xack(JOB_STREAM, CONSUMER_GROUP, message_id)
            return

        job.status = "running"
        db.commit()

        try:
            result = process_job(job.job_type, job.payload)
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            db.commit()
            redis_client.xack(JOB_STREAM, CONSUMER_GROUP, message_id)
            logger.exception("Job %s failed", job_id)
            return

        job.status = "succeeded"
        job.result = result
        db.commit()

    redis_client.xack(JOB_STREAM, CONSUMER_GROUP, message_id)
    logger.info("Job %s completed", job_id)


def run_worker() -> None:
    """Wait for messages and pass each one to the job handler."""
    ensure_consumer_group()
    consumer_name = f"worker-{uuid4().hex[:8]}"
    logger.info("Worker %s is listening on %s", consumer_name, JOB_STREAM)

    while True:
        messages = redis_client.xreadgroup(
            groupname=CONSUMER_GROUP,
            consumername=consumer_name,
            streams={JOB_STREAM: ">"},
            count=1,
            block=5000,
        )

        for _stream_name, entries in messages:
            for message_id, fields in entries:
                handle_message(message_id, fields)


if __name__ == "__main__":
    run_worker()