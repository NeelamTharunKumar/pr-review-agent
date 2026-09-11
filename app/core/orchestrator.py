import asyncio
import logging
import random

from app.agents.fetcher import FetcherAgent
from app.agents.poster import PosterAgent
from app.agents.reviewer import ReviewerAgent
from app.config import settings
from app.core.evaluator import EvaluatorAgent
from app.db.crud import has_reviewed_head, save_evaluation_metrics, save_review
from app.db.database import SessionLocal

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BASE_DELAY = 5
MAX_DELAY = 60


async def run_pipeline(repo_name: str, pr_number: int):

    logger.info(f"[Orchestrator] Pipeline started — Repo: {repo_name} | PR: #{pr_number}")

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.info(f"[Orchestrator] Attempt {attempt}/{MAX_RETRIES}")

            logger.info("[Orchestrator] Stage 1 — Fetching PR data")
            fetcher = FetcherAgent()
            context = await asyncio.to_thread(fetcher.run, repo_name, pr_number)

            logger.info(
                f"[Orchestrator] Stage 1 complete — "
                f"Fetched {len(context.files)} files | "
                f"HEAD: {context.head_sha[:8] if context.head_sha else 'unknown'}"
            )

            logger.info("[Orchestrator] Checking idempotency...")
            db_check = SessionLocal()
            try:
                already_reviewed = await asyncio.to_thread(
                    has_reviewed_head,
                    db_check,
                    context.repo_name,
                    context.pr_number,
                    context.head_sha,
                )
            finally:
                db_check.close()

            if already_reviewed:
                logger.info(
                    f"[Orchestrator] PR #{pr_number} already reviewed "
                    f"at SHA {context.head_sha[:8]} — skipping"
                )
                return

            logger.info("[Orchestrator] Stage 2 — Reviewing code with AI")

            if getattr(settings, "AGENTIC_MODE", False):
                try:
                    from app.agents.agentic_reviewer import AgenticReviewerAgent

                    reviewer = AgenticReviewerAgent()
                    logger.info("[Orchestrator] Using AgenticReviewerAgent")
                except ImportError:
                    logger.warning(
                        "[Orchestrator] AGENTIC_MODE enabled but "
                        "agentic_reviewer not available — falling back"
                    )
                    reviewer = ReviewerAgent()
            else:
                reviewer = ReviewerAgent()
                logger.info("[Orchestrator] Using standard ReviewerAgent")

            result = await asyncio.to_thread(reviewer.run, context)

            logger.info(
                f"[Orchestrator] Stage 2 complete — "
                f"Score: {result.overall_score}/10 | "
                f"Comments: {len(result.comments)}"
            )

            logger.info("[Orchestrator] Stage 3 — Evaluating review quality")
            evaluator = EvaluatorAgent()
            metrics, comment_evaluations = await asyncio.to_thread(evaluator.run, context, result)

            logger.info(
                f"[Orchestrator] Stage 3 complete — "
                f"Quality: {metrics['quality_score']} | "
                f"Hallucination: {metrics['hallucination_rate']}% | "
                f"Coverage: {metrics['coverage_rate']}%"
            )

            logger.info("[Orchestrator] Stage 4 — Posting review to GitHub")
            poster = PosterAgent()
            success = await asyncio.to_thread(poster.run, context, result, comment_evaluations)

            logger.info(f"[Orchestrator] Stage 4 complete — Posted: {success}")

            logger.info("[Orchestrator] Stage 5 — Saving to database")
            db = SessionLocal()
            try:
                saved = await asyncio.to_thread(
                    save_review, db, context, result, success, comment_evaluations
                )
                await asyncio.to_thread(save_evaluation_metrics, db, saved.id, metrics)
                logger.info(f"[Orchestrator] Stage 5 complete — Review ID: {saved.id}")
            finally:
                db.close()

            logger.info(
                f"[Orchestrator] Pipeline finished — "
                f"PR #{pr_number} | Score: {result.overall_score}/10 | "
                f"Approved: {result.approved} | "
                f"Quality: {metrics['quality_score']} | Posted: {success}"
            )
            return

        except Exception as e:
            logger.error(f"[Orchestrator] Attempt {attempt} failed — {type(e).__name__}: {e}")

            if attempt < MAX_RETRIES:
                delay = min(MAX_DELAY, BASE_DELAY * (2 ** (attempt - 1)))
                jitter = random.uniform(0, delay * 0.3)
                sleep_time = delay + jitter
                logger.info(
                    f"[Orchestrator] Retrying in {sleep_time:.1f}s "
                    f"(attempt {attempt + 1}/{MAX_RETRIES})"
                )
                await asyncio.sleep(sleep_time)
            else:
                logger.error(
                    f"[Orchestrator] All {MAX_RETRIES} attempts failed — "
                    f"PR #{pr_number} will not be reviewed"
                )
