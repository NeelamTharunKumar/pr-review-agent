import logging
from app.core.schemas import PRContext, ReviewResult, ReviewComment
from app.core.prompts import build_user_prompt
from app.core.utils import parse_json_response, split_files_into_chunks
from app.llm import llm_client

logger = logging.getLogger(__name__)


REVIEW_PASSES = [
    {
        "name": "Security Analysis",
        "system": (
            "You are a security specialist reviewing a pull request. "
            "Focus ONLY on security vulnerabilities: injection attacks, "
            "auth/authorization flaws, secrets in code, insecure defaults, "
            "SSRF, path traversal, unsafe deserialization, XSS, "
            "insecure dependencies. Ignore style and performance.\n\n"
            "Return ONLY valid JSON with this exact structure:\n"
            '{"overall_score": <1-10>, "approved": <bool>, '
            '"summary": "<2-3 sentences about security posture>", '
            '"comments": [{"filename": "<file>", "line": <int>, '
            '"issue": "<security issue>", "suggestion": "<fix>", '
            '"severity": "<critical|warning>", '
            '"confidence": <float 0.0-1.0>}]}'
        ),
    },
    {
        "name": "Bug Detection & Code Quality",
        "system": (
            "You are a senior software engineer reviewing a pull request. "
            "Focus on: logic errors, unhandled edge cases, race conditions, "
            "resource leaks, type errors, missing error handling, broken "
            "contracts, dead code, and anti-patterns. Ignore security "
            "(another pass handles that).\n\n"
            "Return ONLY valid JSON with this exact structure:\n"
            '{"overall_score": <1-10>, "approved": <bool>, '
            '"summary": "<2-3 sentences about code quality>", '
            '"comments": [{"filename": "<file>", "line": <int>, '
            '"issue": "<quality issue>", "suggestion": "<fix>", '
            '"severity": "<critical|warning|suggestion>", '
            '"confidence": <float 0.0-1.0>}]}'
        ),
    },
    {
        "name": "Performance & Best Practices",
        "system": (
            "You are a performance and architecture specialist reviewing a "
            "pull request. Focus on: N+1 queries, unnecessary allocations, "
            "missing caching opportunities, suboptimal algorithms, "
            "architectural concerns, missing indexes, blocking I/O in "
            "async contexts, and framework-specific best practices.\n\n"
            "Return ONLY valid JSON with this exact structure:\n"
            '{"overall_score": <1-10>, "approved": <bool>, '
            '"summary": "<2-3 sentences about performance>", '
            '"comments": [{"filename": "<file>", "line": <int>, '
            '"issue": "<performance issue>", "suggestion": "<fix>", '
            '"severity": "<warning|suggestion>", '
            '"confidence": <float 0.0-1.0>}]}'
        ),
    },
]


class AgenticReviewerAgent:

    MODEL = "llama-3.3-70b-versatile"
    MAX_TOKENS = 4096
    TEMPERATURE = 0.1
    CHUNK_SIZE = 80000

    def run(self, context: PRContext) -> ReviewResult:
        logger.info(
            f"[AgenticReviewer] Starting multi-pass review for PR #{context.pr_number}"
        )

        user_prompt = build_user_prompt(context)
        logger.info(f"[AgenticReviewer] Prompt size: {len(user_prompt)} chars")

        if len(user_prompt) > self.CHUNK_SIZE:
            logger.info(
                f"[AgenticReviewer] Prompt exceeds {self.CHUNK_SIZE} chars — "
                f"using chunked review"
            )
            return self._review_chunked(context, user_prompt)

        if context.truncated_files:
            for tf in context.truncated_files:
                logger.warning(
                    f"[AgenticReviewer] Truncated file: {tf['filename']} "
                    f"({tf['shown_lines']}/{tf['total_lines']} lines shown)"
                )

        all_comments: list[dict] = []
        scores: list[int] = []

        for i, review_pass in enumerate(REVIEW_PASSES, 1):
            logger.info(f"[AgenticReviewer] Pass {i}/{len(REVIEW_PASSES)}: {review_pass['name']}")

            try:
                raw = llm_client.complete(
                    system=review_pass["system"],
                    user=user_prompt,
                    model=self.MODEL,
                    max_tokens=self.MAX_TOKENS,
                    temperature=self.TEMPERATURE,
                )
                data = parse_json_response(raw)
                all_comments.extend(data.get("comments", []))
                scores.append(data.get("overall_score", 5))

                logger.info(
                    f"[AgenticReviewer] {review_pass['name']} done — "
                    f"Score: {data.get('overall_score', '?')}/10, "
                    f"Comments: {len(data.get('comments', []))}"
                )

            except Exception as e:
                logger.error(
                    f"[AgenticReviewer] Pass {review_pass['name']} failed: {e}"
                )
                scores.append(5)

        merged_comments = self._deduplicate(all_comments)
        avg_score = round(sum(scores) / len(scores)) if scores else 5
        approved = avg_score >= 7 and not any(
            c.get("severity") == "critical" for c in merged_comments
        )

        summary_parts = []
        for i, rp in enumerate(REVIEW_PASSES):
            if i < len(scores):
                summary_parts.append(f"{rp['name']}: {scores[i]}/10")

        comments = []
        for c in merged_comments:
            try:
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
            except (KeyError, ValueError, TypeError) as e:
                logger.warning(f"[AgenticReviewer] Skipping malformed comment: {e}")

        result = ReviewResult(
            overall_score=avg_score,
            approved=approved,
            summary=" | ".join(summary_parts),
            comments=comments,
        )

        logger.info(
            f"[AgenticReviewer] Review complete — "
            f"Score: {result.overall_score}/10 | "
            f"Approved: {result.approved} | "
            f"Comments: {len(result.comments)}"
        )

        return result

    def _deduplicate(self, comments: list[dict]) -> list[dict]:
        seen: dict[tuple, dict] = {}
        severity_order = {"critical": 0, "warning": 1, "suggestion": 2}

        for c in comments:
            if not c.get("filename") or c.get("line") is None or not c.get("issue"):
                continue
            key = (c.get("filename"), c.get("line"), c.get("issue", "")[:40])
            if key in seen:
                existing_sev = severity_order.get(seen[key].get("severity"), 2)
                new_sev = severity_order.get(c.get("severity"), 2)
                if new_sev < existing_sev:
                    seen[key] = c
                elif new_sev == existing_sev:
                    existing_conf = seen[key].get("confidence", 1.0)
                    new_conf = c.get("confidence", 1.0)
                    try:
                        if float(new_conf) > float(existing_conf):
                            seen[key] = c
                    except (TypeError, ValueError):
                        pass
            else:
                seen[key] = c

        deduped = list(seen.values())
        deduped.sort(key=lambda x: severity_order.get(x.get("severity"), 2))

        logger.info(
            f"[AgenticReviewer] Deduplicated {len(comments)} → {len(deduped)} comments"
        )
        return deduped

    def _review_chunked(
        self, context: PRContext, full_prompt: str
    ) -> ReviewResult:
        file_chunks = split_files_into_chunks(context.files, self.CHUNK_SIZE)
        logger.info(
            f"[AgenticReviewer] Split into {len(file_chunks)} chunks"
        )

        all_comments: list[dict] = []
        scores: list[int] = []

        for i, chunk_files in enumerate(file_chunks, 1):
            logger.info(
                f"[AgenticReviewer] Chunk {i}/{len(file_chunks)}"
            )

            chunk_context = PRContext(
                repo_name=context.repo_name,
                pr_number=context.pr_number,
                title=context.title,
                description=context.description,
                author=context.author,
                base_branch=context.base_branch,
                head_branch=context.head_branch,
                head_sha=context.head_sha,
                files=chunk_files,
                repo_context=context.repo_context,
                rag_context=context.rag_context,
            )

            chunk_prompt = build_user_prompt(chunk_context)

            for review_pass in REVIEW_PASSES:
                try:
                    raw = llm_client.complete(
                        system=review_pass["system"],
                        user=chunk_prompt,
                        model=self.MODEL,
                        max_tokens=self.MAX_TOKENS,
                        temperature=self.TEMPERATURE,
                    )
                    data = parse_json_response(raw)
                    all_comments.extend(data.get("comments", []))
                    scores.append(data.get("overall_score", 5))

                    logger.info(
                        f"[AgenticReviewer] Chunk {i} / {review_pass['name']} done"
                    )

                except Exception as e:
                    logger.error(
                        f"[AgenticReviewer] Chunk {i} / {review_pass['name']} failed: {e}"
                    )
                    scores.append(5)

        merged_comments = self._deduplicate(all_comments)
        avg_score = round(sum(scores) / len(scores)) if scores else 5
        approved = avg_score >= 7 and not any(
            c.get("severity") == "critical" for c in merged_comments
        )

        result = ReviewResult(
            overall_score=avg_score,
            approved=approved,
            summary=f"Chunked agentic review ({len(file_chunks)} chunks). Avg: {avg_score}/10",
            comments=[
                ReviewComment(
                    filename=c["filename"],
                    line=c["line"],
                    issue=c["issue"],
                    suggestion=c["suggestion"],
                    severity=c["severity"],
                    confidence=float(c.get("confidence", 1.0)),
                )
                for c in merged_comments
            ],
        )

        logger.info(
            f"[AgenticReviewer] Chunked review complete — "
            f"Score: {result.overall_score}/10 | "
            f"Comments: {len(result.comments)}"
        )
        return result
