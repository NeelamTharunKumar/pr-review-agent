import logging
from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="app.tasks.review_pr", max_retries=3)
def review_pr(self, repo_name: str, pr_number: int):
    import asyncio
    from app.core.orchestrator import run_pipeline

    logger.info(
        f"[Celery] Task review_pr started — "
        f"Repo: {repo_name} | PR: #{pr_number}"
    )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run_pipeline(repo_name, pr_number))
        finally:
            loop.close()

        logger.info(
            f"[Celery] Task review_pr completed — "
            f"Repo: {repo_name} | PR: #{pr_number}"
        )
        return {"status": "completed", "repo": repo_name, "pr": pr_number}

    except Exception as exc:
        logger.error(
            f"[Celery] Task review_pr failed — {type(exc).__name__}: {exc}"
        )
        raise self.retry(exc=exc, countdown=60 * (self.request.retries + 1))


@celery_app.task(bind=True, name="app.tasks.ingest_repo", max_retries=2)
def ingest_repo(self, repo_name: str):
    from app.rag.ingestor import CodebaseIngestor

    logger.info(f"[Celery] Task ingest_repo started — {repo_name}")

    try:
        ingestor = CodebaseIngestor()
        result = ingestor.ingest_repo(repo_name)

        logger.info(f"[Celery] Task ingest_repo completed — {result}")
        return {"status": "completed", **result}

    except Exception as exc:
        logger.error(
            f"[Celery] Task ingest_repo failed — {type(exc).__name__}: {exc}"
        )
        raise self.retry(exc=exc, countdown=120)
