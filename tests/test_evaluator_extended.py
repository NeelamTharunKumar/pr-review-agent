from app.core.evaluator import EvaluatorAgent
from app.core.schemas import ChangedFile, PRContext, ReviewComment, ReviewResult


class TestEvaluatorEdgeCases:
    def test_empty_comments(self):
        ctx = PRContext(
            repo_name="t/r",
            pr_number=1,
            title="T",
            description="",
            author="a",
            base_branch="main",
            head_branch="feat",
            files=[
                ChangedFile(
                    filename="a.py",
                    status="modified",
                    additions=5,
                    deletions=0,
                    patch="@@ +1,5 @@\n+line1\n+line2\n+line3\n+line4\n+line5",
                )
            ],
        )
        result = ReviewResult(overall_score=8, approved=True, summary="Good", comments=[])
        evaluator = EvaluatorAgent()
        metrics, evals = evaluator.run(ctx, result)
        assert metrics["total_comments"] == 0
        assert metrics["hallucinated_comments"] == 0
        assert metrics["hallucination_rate"] == 0.0
        assert evals == []

    def test_empty_files(self):
        ctx = PRContext(
            repo_name="t/r",
            pr_number=1,
            title="T",
            description="",
            author="a",
            base_branch="main",
            head_branch="feat",
            files=[],
        )
        result = ReviewResult(
            overall_score=8,
            approved=True,
            summary="Good",
            comments=[
                ReviewComment(
                    filename="a.py", line=1, issue="X", suggestion="Y", severity="warning"
                ),
            ],
        )
        evaluator = EvaluatorAgent()
        metrics, _evals = evaluator.run(ctx, result)
        assert metrics["hallucinated_comments"] == 1
        assert metrics["hallucination_rate"] == 100.0

    def test_all_valid_comments(self):
        ctx = PRContext(
            repo_name="t/r",
            pr_number=1,
            title="T",
            description="",
            author="a",
            base_branch="main",
            head_branch="feat",
            files=[
                ChangedFile(
                    filename="a.py",
                    status="modified",
                    additions=5,
                    deletions=0,
                    patch="@@ +1,5 @@\n+line1\n+line2\n+line3\n+line4\n+line5",
                )
            ],
        )
        result = ReviewResult(
            overall_score=8,
            approved=True,
            summary="Good",
            comments=[
                ReviewComment(
                    filename="a.py", line=1, issue="X", suggestion="Y", severity="warning"
                ),
                ReviewComment(
                    filename="a.py", line=3, issue="X", suggestion="Y", severity="warning"
                ),
            ],
        )
        evaluator = EvaluatorAgent()
        metrics, evals = evaluator.run(ctx, result)
        assert metrics["hallucinated_comments"] == 0
        assert evals == [True, True]

    def test_mixed_valid_invalid(self):
        ctx = PRContext(
            repo_name="t/r",
            pr_number=1,
            title="T",
            description="",
            author="a",
            base_branch="main",
            head_branch="feat",
            files=[
                ChangedFile(
                    filename="a.py",
                    status="modified",
                    additions=5,
                    deletions=0,
                    patch="@@ +1,5 @@\n+line1\n+line2\n+line3\n+line4\n+line5",
                )
            ],
        )
        result = ReviewResult(
            overall_score=8,
            approved=True,
            summary="Good",
            comments=[
                ReviewComment(
                    filename="a.py", line=1, issue="X", suggestion="Y", severity="warning"
                ),
                ReviewComment(
                    filename="a.py", line=50, issue="X", suggestion="Y", severity="warning"
                ),
                ReviewComment(
                    filename="nonexistent.py", line=1, issue="X", suggestion="Y", severity="warning"
                ),
            ],
        )
        evaluator = EvaluatorAgent()
        metrics, evals = evaluator.run(ctx, result)
        assert metrics["hallucinated_comments"] == 2
        assert evals == [True, False, False]

    def test_quality_score_calculation(self):
        ctx = PRContext(
            repo_name="t/r",
            pr_number=1,
            title="T",
            description="",
            author="a",
            base_branch="main",
            head_branch="feat",
            files=[
                ChangedFile(
                    filename="a.py",
                    status="modified",
                    additions=5,
                    deletions=0,
                    patch="@@ +1,5 @@\n+line1\n+line2\n+line3\n+line4\n+line5",
                )
            ],
        )
        result = ReviewResult(
            overall_score=8,
            approved=True,
            summary="Good",
            comments=[
                ReviewComment(
                    filename="a.py",
                    line=1,
                    issue="X",
                    suggestion="Y",
                    severity="warning",
                    confidence=0.9,
                ),
                ReviewComment(
                    filename="a.py",
                    line=3,
                    issue="X",
                    suggestion="Y",
                    severity="warning",
                    confidence=0.9,
                ),
            ],
        )
        evaluator = EvaluatorAgent()
        metrics, _evals = evaluator.run(ctx, result)
        assert metrics["quality_score"] > 90.0

    def test_coverage_rate(self):
        ctx = PRContext(
            repo_name="t/r",
            pr_number=1,
            title="T",
            description="",
            author="a",
            base_branch="main",
            head_branch="feat",
            files=[
                ChangedFile(
                    filename="a.py",
                    status="modified",
                    additions=3,
                    deletions=0,
                    patch="@@ +1,3 @@\n+a\n+b\n+c",
                ),
                ChangedFile(
                    filename="b.py",
                    status="modified",
                    additions=3,
                    deletions=0,
                    patch="@@ +1,3 @@\n+a\n+b\n+c",
                ),
            ],
        )
        result = ReviewResult(
            overall_score=8,
            approved=True,
            summary="Good",
            comments=[
                ReviewComment(
                    filename="a.py", line=1, issue="X", suggestion="Y", severity="warning"
                ),
            ],
        )
        evaluator = EvaluatorAgent()
        metrics, _evals = evaluator.run(ctx, result)
        assert metrics["files_covered"] == 1
        assert metrics["total_files"] == 2
        assert metrics["coverage_rate"] == 50.0

    def test_average_confidence(self):
        ctx = PRContext(
            repo_name="t/r",
            pr_number=1,
            title="T",
            description="",
            author="a",
            base_branch="main",
            head_branch="feat",
            files=[
                ChangedFile(
                    filename="a.py",
                    status="modified",
                    additions=5,
                    deletions=0,
                    patch="@@ +1,5 @@\n+line1\n+line2\n+line3\n+line4\n+line5",
                )
            ],
        )
        result = ReviewResult(
            overall_score=8,
            approved=True,
            summary="Good",
            comments=[
                ReviewComment(
                    filename="a.py",
                    line=1,
                    issue="X",
                    suggestion="Y",
                    severity="warning",
                    confidence=0.5,
                ),
                ReviewComment(
                    filename="a.py",
                    line=3,
                    issue="X",
                    suggestion="Y",
                    severity="warning",
                    confidence=0.9,
                ),
            ],
        )
        evaluator = EvaluatorAgent()
        metrics, _evals = evaluator.run(ctx, result)
        assert metrics["average_confidence"] == 0.7

    def test_quality_score_capped_at_100(self):
        ctx = PRContext(
            repo_name="t/r",
            pr_number=1,
            title="T",
            description="",
            author="a",
            base_branch="main",
            head_branch="feat",
            files=[
                ChangedFile(
                    filename="a.py",
                    status="modified",
                    additions=5,
                    deletions=0,
                    patch="@@ +1,5 @@\n+a\n+b\n+c\n+d\n+e",
                )
            ],
        )
        result = ReviewResult(
            overall_score=10,
            approved=True,
            summary="Perfect",
            comments=[
                ReviewComment(
                    filename="a.py",
                    line=1,
                    issue="X",
                    suggestion="Y",
                    severity="suggestion",
                    confidence=1.0,
                ),
            ],
        )
        evaluator = EvaluatorAgent()
        metrics, _evals = evaluator.run(ctx, result)
        assert metrics["quality_score"] <= 100.0

    def test_quality_score_floored_at_zero(self):
        ctx = PRContext(
            repo_name="t/r",
            pr_number=1,
            title="T",
            description="",
            author="a",
            base_branch="main",
            head_branch="feat",
            files=[
                ChangedFile(
                    filename="a.py",
                    status="modified",
                    additions=5,
                    deletions=0,
                    patch="@@ +1,5 @@\n+a\n+b\n+c\n+d\n+e",
                )
            ],
        )
        result = ReviewResult(
            overall_score=1,
            approved=False,
            summary="Bad",
            comments=[
                ReviewComment(
                    filename="a.py",
                    line=50,
                    issue="X",
                    suggestion="Y",
                    severity="critical",
                    confidence=0.0,
                ),
                ReviewComment(
                    filename="a.py",
                    line=60,
                    issue="X",
                    suggestion="Y",
                    severity="critical",
                    confidence=0.0,
                ),
                ReviewComment(
                    filename="nonexistent.py",
                    line=1,
                    issue="X",
                    suggestion="Y",
                    severity="critical",
                    confidence=0.0,
                ),
            ],
        )
        evaluator = EvaluatorAgent()
        metrics, _evals = evaluator.run(ctx, result)
        assert metrics["quality_score"] >= 0.0
