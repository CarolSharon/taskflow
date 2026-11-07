from uuid import UUID

from app.redis_client import redis_client

JOB_STREAM = "taskflow:jobs"


def enqueue_job(job_id: UUID, job_type: str) -> str:
    """Add a job reference to the Redis Stream and return its message ID."""
    message_id = redis_client.xadd(
        JOB_STREAM,
        {
            "job_id": str(job_id),
            "job_type": job_type,
        },
    )
    return message_id