import logging
from app.core.schemas import PRContext, ReviewResult
from app.core.utils import parse_diff_new_file_lines

logger = logging.getLogger(__name__)


class EvaluatorAgent:

    def run(
        self,
        context: PRContext,
        result: ReviewResult
    ) -> tuple[dict, list[bool]]:
        logger.info(
            f"[EvaluatorAgent] Evaluating review for "
            f"PR #{context.pr_number}"
        )

        file_line_sets = self._build_file_line_sets(context)
        comment_evaluations = self._evaluate_comments(
            result, file_line_sets
        )
        metrics = self._compute_metrics(
            context, result, comment_evaluations
        )

        logger.info(
            f"[EvaluatorAgent] Evaluation complete — "
            f"Quality: {metrics['quality_score']:.1f} | "
            f"Hallucination rate: {metrics['hallucination_rate']:.1f}% | "
            f"Coverage: {metrics['coverage_rate']:.1f}%"
        )

        return metrics, comment_evaluations

    def _build_file_line_sets(self, context: PRContext) -> dict:
        file_line_sets = {}

        for changed_file in context.files:
            file_line_sets[changed_file.filename] = parse_diff_new_file_lines(
                changed_file.patch or ""
            )

        logger.info(
            f"[EvaluatorAgent] Built line sets for "
            f"{len(file_line_sets)} files"
        )

        return file_line_sets

    def _evaluate_comments(
        self,
        result: ReviewResult,
        file_line_sets: dict
    ) -> list:
        evaluations = []

        for comment in result.comments:
            filename = comment.filename
            line = comment.line

            if filename not in file_line_sets:
                logger.warning(
                    f"[EvaluatorAgent] HALLUCINATION — "
                    f"File '{filename}' does not exist in this PR"
                )
                evaluations.append(False)
                continue

            valid_lines = file_line_sets[filename]

            if line not in valid_lines:
                logger.warning(
                    f"[EvaluatorAgent] HALLUCINATION — "
                    f"Line {line} does not exist in '{filename}' "
                    f"(diff has {len(valid_lines)} new-file lines)"
                )
                evaluations.append(False)
                continue

            logger.info(
                f"[EvaluatorAgent] VALID — "
                f"'{filename}' line {line} exists in diff"
            )
            evaluations.append(True)

        return evaluations

    def _compute_metrics(
        self,
        context: PRContext,
        result: ReviewResult,
        comment_evaluations: list
    ) -> dict:

        total_comments = len(result.comments)

        if total_comments > 0:
            hallucinated = comment_evaluations.count(False)
            hallucination_rate = (hallucinated / total_comments) * 100

            confidences = [c.confidence for c in result.comments]
            avg_confidence = sum(confidences) / len(confidences)
        else:
            hallucinated = 0
            hallucination_rate = 0.0
            avg_confidence = 0.0

        commented_files = set(
            c.filename for c in result.comments
        )
        total_files = len(context.files)
        files_covered = len(
            commented_files & set(
                f.filename for f in context.files
            )
        )

        if total_files > 0:
            coverage_rate = (files_covered / total_files) * 100
        else:
            coverage_rate = 0.0

        quality_score = 100.0
        quality_score -= hallucination_rate * 0.5
        quality_score += coverage_rate * 0.1
        quality_score += (avg_confidence - 0.5) * 10
        quality_score = max(0.0, min(100.0, quality_score))

        metrics = {
            "total_comments": total_comments,
            "hallucinated_comments": hallucinated,
            "hallucination_rate": round(hallucination_rate, 2),
            "files_covered": files_covered,
            "total_files": total_files,
            "coverage_rate": round(coverage_rate, 2),
            "quality_score": round(quality_score, 2),
            "average_confidence": round(avg_confidence, 3),
        }

        return metrics
