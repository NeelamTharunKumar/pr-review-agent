import hmac
import hashlib
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from app.config import settings
from app.db.database import init_db
from app.logging_config import setup_logging

setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT)
logger = logging.getLogger(__name__)

_REQUEST_START: dict[str, float] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("PR Review Agent starting up...")
    init_db()
    yield
    logger.info("PR Review Agent shutting down...")


app = FastAPI(
    title="PR Review Agent",
    description="AI-powered GitHub Pull Request reviewer",
    version="2.0.0",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", "")
    start = time.time()
    response = await call_next(request)
    elapsed = round((time.time() - start) * 1000)
    logger.info(
        f"[HTTP] {request.method} {request.url.path} "
        f"→ {response.status_code} ({elapsed}ms)"
        + (f" [{request_id}]" if request_id else "")
    )
    return response


def verify_github_signature(payload: bytes, signature: str) -> bool:
    expected_signature = "sha256=" + hmac.new(
        settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature)


def _dispatch_pipeline(repo_name: str, pr_number: int):
    if settings.USE_CELERY:
        from app.tasks import review_pr
        review_pr.delay(repo_name, pr_number)
        logger.info(f"[Webhook] Pipeline dispatched to Celery for PR #{pr_number}")
    else:
        from app.core.orchestrator import run_pipeline
        import asyncio

        async def _run():
            await run_pipeline(repo_name, pr_number)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()


def _dispatch_ingestion(repo_name: str):
    if settings.USE_CELERY:
        from app.tasks import ingest_repo
        ingest_repo.delay(repo_name)
        logger.info(f"[API] Ingestion dispatched to Celery for {repo_name}")
    else:
        from app.rag.ingestor import CodebaseIngestor

        def run_ingestion():
            ingestor = CodebaseIngestor()
            result = ingestor.ingest_repo(repo_name)
            logger.info(f"[API] Ingestion complete: {result}")

        import threading
        threading.Thread(target=run_ingestion, daemon=True).start()


@app.post("/ingest/{repo_owner}/{repo_name}")
async def ingest_repo(repo_owner: str, repo_name: str, background_tasks: BackgroundTasks):
    full_repo_name = f"{repo_owner}/{repo_name}"
    logger.info(f"[API] Ingestion requested for {full_repo_name}")

    background_tasks.add_task(_dispatch_ingestion, full_repo_name)

    return {
        "status": "ingestion_started",
        "repo": full_repo_name,
        "message": "Codebase is being indexed. Reviews will use RAG context once complete.",
    }


@app.get("/health")
async def health_check():
    health = {"status": "healthy", "service": "PR Review Agent", "version": "2.0.0"}

    if settings.USE_CELERY:
        try:
            from app.celery_app import celery_app
            inspect = celery_app.control.inspect(timeout=2)
            active = inspect.active()
            health["celery"] = "connected" if active else "no workers"
        except Exception:
            health["celery"] = "unreachable"

    return health


@app.get("/metrics")
async def get_metrics():
    from app.db.database import SessionLocal
    from app.db.crud import get_evaluation_report, get_stats

    db = SessionLocal()
    try:
        report = get_evaluation_report(db)
        stats = get_stats(db)
        return {"system_stats": stats, "ai_quality": report}
    finally:
        db.close()


@app.get("/reviews/{repo_owner}/{repo_name}")
async def list_reviews(repo_owner: str, repo_name: str, limit: int = 20):
    from app.db.database import SessionLocal
    from app.db.crud import get_all_reviews

    full_repo = f"{repo_owner}/{repo_name}"
    db = SessionLocal()
    try:
        reviews = get_all_reviews(db, limit=limit)
        repo_reviews = [
            {
                "id": r.id,
                "pr_number": r.pr_number,
                "pr_title": r.pr_title,
                "overall_score": r.overall_score,
                "approved": r.approved,
                "posted": r.posted_successfully,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in reviews
            if r.repo_name == full_repo
        ]
        return {"repo": full_repo, "reviews": repo_reviews, "count": len(repo_reviews)}
    finally:
        db.close()


@app.post("/webhook/github", status_code=202)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
):
    payload_bytes = await request.body()
    github_signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_github_signature(payload_bytes, github_signature):
        logger.warning("[Webhook] Rejected — invalid signature")
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    event_type = request.headers.get("X-GitHub-Event", "")
    payload = await request.json()

    if event_type != "pull_request":
        logger.info(f"[Webhook] Ignoring event type: {event_type}")
        return {"status": "ignored", "reason": f"Event type '{event_type}' not handled"}

    action = payload.get("action", "")
    if action not in ("opened", "synchronize"):
        logger.info(f"[Webhook] Ignoring pull_request action: {action}")
        return {"status": "ignored", "reason": f"Action '{action}' not handled"}

    pr_number = payload["pull_request"]["number"]
    repo_name = payload["repository"]["full_name"]

    logger.info(
        f"[Webhook] Received pull_request — "
        f"Repo: {repo_name} | PR: #{pr_number} | Action: {action}"
    )

    background_tasks.add_task(_dispatch_pipeline, repo_name, pr_number)

    return {
        "status": "accepted",
        "message": f"Review queued for PR #{pr_number} in {repo_name}",
    }
