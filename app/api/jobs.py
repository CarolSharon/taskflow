from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Job
from app.db.session import get_db
from app.schemas.jobs import JobCreate, JobRead
from app.queue import enqueue_job
router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(
    job_data: JobCreate,
    response: Response,
    db: Session = Depends(get_db),
) -> Job:
    """Save a new job, or return the existing job for a repeated key."""
    key = job_data.idempotency_key

    if key:
        existing = db.scalar(
            select(Job).where(Job.idempotency_key == key)
        )
        if existing:
            if (
                existing.job_type != job_data.job_type
                or existing.payload != job_data.payload
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This idempotency key was already used for different job data.",
                )
            response.status_code = status.HTTP_200_OK
            return existing

    job = Job(
        job_type=job_data.job_type,
        payload=job_data.payload,
        idempotency_key=key,
    )
    db.add(job)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()

        # Another request may have inserted the same key at the same time.
        if key:
            existing = db.scalar(
                select(Job).where(Job.idempotency_key == key)
            )
            if existing:
                if (
                    existing.job_type == job_data.job_type
                    and existing.payload == job_data.payload
                ):
                    response.status_code = status.HTTP_200_OK
                    return existing

                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This idempotency key was already used for different job data.",
                ) from exc

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The job could not be saved because it conflicts with existing data.",
        ) from exc

    db.refresh(job)
    enqueue_job(job.id, job.job_type)
    return job


@router.get("/{job_id}", response_model=JobRead)
def get_job(
    job_id: UUID,
    db: Session = Depends(get_db),
) -> Job:
    """Return one job, or a 404 response if it does not exist."""
    job = db.get(Job, job_id)

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Job not found",
        )

    return job