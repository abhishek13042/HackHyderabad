"""Demo controls: seed history and reset everything (SPEC-07 §3)."""

import logging

from fastapi import APIRouter, BackgroundTasks, status

from backend.app.memory import MemoryUnavailableError
from backend.app.routers.common import (
    ServicesDep,
    SessionDep,
    claim_work,
    conflict,
    memory_offline,
    not_found,
)
from backend.app.schemas import JobOut, ResetIn, ResetOut
from backend.app.seed import FIRM_FILE, load_dataset, seed, seed_plan
from backend.app.services import Job, Services
from backend.app.store import RunRow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/demo")


@router.post("/seed", status_code=status.HTTP_202_ACCEPTED)
def start_seed(services: ServicesDep, session: SessionDep, background: BackgroundTasks) -> JobOut:
    """Load the generated dataset and replay all periods but the last; poll `/demo/jobs/{id}`."""
    if not (services.data_dir / FIRM_FILE).is_file():
        raise not_found(f"no dataset in {services.data_dir}; run `python -m backend.datagen`")
    claim_work(services, "seed")
    if session.store.has_data():
        services.work.release()
        raise conflict("the database already has data; reset the demo first")
    job = services.new_job("seed")
    background.add_task(_seed, services, job)
    return job_out(job)


def _seed(services: Services, job: Job) -> None:
    def progress(run: RunRow) -> None:
        job.done += 1
        job.result["last"] = f"{run.client_id} {run.period}"

    try:
        with services.session() as session:
            load_dataset(session.store, services.data_dir)
            services.memory.ensure_bank(services.bank_profile(session.store))
            job.total = len(seed_plan(session.store))
            runs = seed(session.pipeline, services.data_dir, on_run=progress)
            job.result = {"runs": len(runs), "periods": sorted({r.period for r in runs})}
        job.status = "done"
    except Exception as exc:
        logger.exception("seed job %s failed", job.id)
        job.status, job.error = "failed", f"{type(exc).__name__}: {exc}"
    finally:
        services.work.release()


@router.get("/jobs/{job_id}")
def get_job(job_id: str, services: ServicesDep) -> JobOut:
    job = services.jobs.get(job_id)
    if job is None:
        raise not_found(f"no job {job_id}")
    return job_out(job)


def job_out(job: Job) -> JobOut:
    return JobOut(
        job_id=job.id,
        kind=job.kind,
        status=job.status,
        done=job.done,
        total=job.total,
        error=job.error,
        result=job.result,
    )


@router.post("/reset")
def reset(body: ResetIn, services: ServicesDep, session: SessionDep) -> ResetOut:
    """Delete and recreate the memory bank, then empty the database. Memory goes first: if
    Hindsight is down nothing is wiped, so the two never disagree."""
    claim_work(services, "reset")
    try:
        profile = services.bank_profile(session.store)
        try:
            services.memory.reset_bank(profile)
        except MemoryUnavailableError as exc:
            raise memory_offline() from exc
        session.store.wipe()
        services.jobs.clear()
    finally:
        services.work.release()
    return ResetOut(reset=body.confirm == "RESET")
