import logging

from app.config import settings
from app.core.prompts import SYSTEM_PROMPT, build_user_prompt
from app.core.schemas import PRContext, ReviewComment, ReviewResult
from app.core.utils import SKIP_PATTERNS, parse_json_response, split_files_into_chunks
from app.llm import llm_client

logger = logging.getLogger(__name__)


class ReviewerAgent:
    MODEL = "llama-3.3-70b-versatile"
    MAX_TOKENS = 4096
    TEMPERATURE = 0.1
    CHUNK_SIZE = 80000

    def run(self, context: PRContext) -> ReviewResult:
        logger.info(f"[ReviewerAgent] Starting review for PR #{context.pr_number}")

        user_prompt = build_user_prompt(context)

        prompt_length = len(user_prompt)
        logger.info(f"[ReviewerAgent] Prompt size: {prompt_length} characters")

        if context.truncated_files:
            truncated_count = len(context.truncated_files)
            logger.warning(
                f"[ReviewerAgent] WARNING: {truncated_count} file(s) were truncated. "
                f"Review may be incomplete."
            )
            for tf in context.truncated_files:
                logger.warning(
                    f"  - {tf['filename']}: {tf['total_lines']} lines total, "
                    f"only first {tf['shown_lines']} shown"
                )

        if prompt_length > self.CHUNK_SIZE:
            logger.info(
                f"[ReviewerAgent] Prompt exceeds {self.CHUNK_SIZE} chars — using chunked review"
            )
            return self._review_chunked(context, user_prompt)

        logger.info(f"[ReviewerAgent] Sending prompt to {self.MODEL}")

        try:
            raw_response = llm_client.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                model=self.MODEL,
                max_tokens=self.MAX_TOKENS,
                temperature=self.TEMPERATURE,
            )
        except Exception as e:
            logger.error(f"[ReviewerAgent] LLM call failed: {e}")
            raise

        logger.info("[ReviewerAgent] Received response from LLM")

        review_data = parse_json_response(raw_response)
        result = self._build_result(review_data)

        logger.info(
            f"[ReviewerAgent] Review complete. "
            f"Score: {result.overall_score}/10 | "
            f"Approved: {result.approved} | "
            f"Comments: {len(result.comments)}"
        )

        return result

    def _review_chunked(self, context: PRContext, full_prompt: str) -> ReviewResult:
        header_lines = []
        in_diff = False

        for line in full_prompt.split("\n"):
            if line.startswith("=" * 60) and "CODE CHANGES" in line:
                in_diff = True
                header_lines.append(line)
                continue
            if in_diff and line.startswith("=" * 60):
                in_diff = False
                header_lines.append(line)
                continue
            if not in_diff:
                header_lines.append(line)

        header = "\n".join(header_lines)
        footer = "\nProvide your repo-aware structured JSON review now:\n"

        file_chunks = split_files_into_chunks(context.files, self.CHUNK_SIZE)
        logger.info(
            f"[ReviewerAgent] Split into {len(file_chunks)} chunks "
            f"({[len(c) for c in file_chunks]} files each)"
        )

        all_comments: list[dict] = []
        scores: list[int] = []

        for i, chunk in enumerate(file_chunks, 1):
            logger.info(f"[ReviewerAgent] Reviewing chunk {i}/{len(file_chunks)}")

            chunk_prompt = header + "\n"
            for f in chunk:
                if not f.patch:
                    continue
                if any(p in f.filename for p in SKIP_PATTERNS):
                    continue
                chunk_prompt += f"\nFile   : {f.filename}\n"
                chunk_prompt += f"Status : {f.status}\n"
                chunk_prompt += f"Changes: +{f.additions} additions, "
                chunk_prompt += f"-{f.deletions} deletions\n"
                chunk_prompt += "Diff:\n"

                diff_lines_f = f.patch.split("\n")
                if len(diff_lines_f) > settings.MAX_DIFF_LINES_PER_FILE:
                    truncated = "\n".join(diff_lines_f[: settings.MAX_DIFF_LINES_PER_FILE])
                    chunk_prompt += truncated
                    omitted = len(diff_lines_f) - settings.MAX_DIFF_LINES_PER_FILE
                    chunk_prompt += (
                        f"\n... [diff truncated — "
                        f"{settings.MAX_DIFF_LINES_PER_FILE} lines shown, "
                        f"{omitted} omitted] ...\n"
                    )
                else:
                    chunk_prompt += f.patch
                chunk_prompt += "\n"

            if context.rag_context:
                chunk_prompt += "=" * 60 + "\n"
                chunk_prompt += "SEMANTICALLY RELATED CODE FROM THE CODEBASE\n"
                chunk_prompt += "=" * 60 + "\n"
                chunk_prompt += context.rag_context + "\n\n"

            chunk_prompt += footer

            try:
                raw_response = llm_client.complete(
                    system=SYSTEM_PROMPT,
                    user=chunk_prompt,
                    model=self.MODEL,
                    max_tokens=self.MAX_TOKENS,
                    temperature=self.TEMPERATURE,
                )
                data = parse_json_response(raw_response)
                all_comments.extend(data.get("comments", []))
                scores.append(data.get("overall_score", 5))

                logger.info(
                    f"[ReviewerAgent] Chunk {i} done — Score: {data.get('overall_score', '?')}/10"
                )

            except Exception as e:
                logger.error(f"[ReviewerAgent] Chunk {i} failed: {e}")
                scores.append(5)

        avg_score = round(sum(scores) / len(scores)) if scores else 5
        approved = avg_score >= 7 and not any(c.get("severity") == "critical" for c in all_comments)

        result = ReviewResult(
            overall_score=avg_score,
            approved=approved,
            summary=(f"Chunked review ({len(file_chunks)} chunks). Average score: {avg_score}/10"),
            comments=[
                ReviewComment(
                    filename=c["filename"],
                    line=c["line"],
                    issue=c["issue"],
                    suggestion=c["suggestion"],
                    severity=c["severity"],
                    confidence=float(c.get("confidence", 1.0)),
                )
                for c in all_comments
            ],
        )

        logger.info(
            f"[ReviewerAgent] Chunked review complete — "
            f"Score: {result.overall_score}/10 | "
            f"Comments: {len(result.comments)}"
        )
        return result

    def _build_result(self, data: dict) -> ReviewResult:
        try:
            comments = []
            for c in data.get("comments", []):
                confidence = c.get("confidence", 1.0)
                try:
                    confidence = float(confidence)
                except (TypeError, ValueError):
                    confidence = 1.0
                confidence = max(0.0, min(1.0, confidence))

                comments.append(
                    ReviewComment(
                        filename=c["filename"],
                        line=c["line"],
                        issue=c["issue"],
                        suggestion=c["suggestion"],
                        severity=c["severity"],
                        confidence=confidence,
                    )
                )

            result = ReviewResult(
                overall_score=data["overall_score"],
                approved=data["approved"],
                summary=data["summary"],
                comments=comments,
            )

            return result

        except (KeyError, ValueError, TypeError) as e:
            logger.error(f"[ReviewerAgent] Failed to build ReviewResult: {e}")
            logger.error(f"[ReviewerAgent] Data received: {data}")

            return ReviewResult(
                overall_score=5,
                approved=False,
                summary="Review structure was invalid. Please review manually.",
                comments=[],
            )
