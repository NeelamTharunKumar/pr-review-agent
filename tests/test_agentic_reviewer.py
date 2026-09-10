import pytest
from unittest.mock import patch, MagicMock
from app.agents.agentic_reviewer import AgenticReviewerAgent
from app.core.schemas import PRContext, ChangedFile, ReviewResult


@pytest.fixture
def reviewer():
    return AgenticReviewerAgent()


class TestAgenticDeduplicate:
    def test_basic_dedup(self, reviewer):
        comments = [
            {"filename": "a.py", "line": 1, "issue": "Bug", "suggestion": "Fix", "severity": "warning"},
            {"filename": "a.py", "line": 1, "issue": "Bug", "suggestion": "Fix", "severity": "critical"},
        ]
        result = reviewer._deduplicate(comments)
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    def test_severity_ordering(self, reviewer):
        comments = [
            {"filename": "a.py", "line": 1, "issue": "Bug", "suggestion": "Fix", "severity": "suggestion"},
            {"filename": "a.py", "line": 1, "issue": "Bug", "suggestion": "Fix", "severity": "critical"},
            {"filename": "a.py", "line": 1, "issue": "Bug", "suggestion": "Fix", "severity": "warning"},
        ]
        result = reviewer._deduplicate(comments)
        assert len(result) == 1
        assert result[0]["severity"] == "critical"

    def test_different_files_not_deduped(self, reviewer):
        comments = [
            {"filename": "a.py", "line": 1, "issue": "Bug", "suggestion": "Fix", "severity": "warning"},
            {"filename": "b.py", "line": 1, "issue": "Bug", "suggestion": "Fix", "severity": "warning"},
        ]
        result = reviewer._deduplicate(comments)
        assert len(result) == 2

    def test_different_lines_not_deduped(self, reviewer):
        comments = [
            {"filename": "a.py", "line": 1, "issue": "Bug", "suggestion": "Fix", "severity": "warning"},
            {"filename": "a.py", "line": 5, "issue": "Bug", "suggestion": "Fix", "severity": "warning"},
        ]
        result = reviewer._deduplicate(comments)
        assert len(result) == 2

    def test_missing_fields_skipped(self, reviewer):
        comments = [
            {"filename": "a.py", "line": None, "issue": "Bug", "suggestion": "Fix", "severity": "warning"},
            {"filename": "", "line": 1, "issue": "Bug", "suggestion": "Fix", "severity": "warning"},
            {"filename": "a.py", "line": 1, "issue": "", "suggestion": "Fix", "severity": "warning"},
        ]
        result = reviewer._deduplicate(comments)
        assert len(result) == 0

    def test_empty_list(self, reviewer):
        assert reviewer._deduplicate([]) == []

    def test_sorted_by_severity(self, reviewer):
        comments = [
            {"filename": "a.py", "line": 1, "issue": "A", "suggestion": "Fix", "severity": "suggestion"},
            {"filename": "a.py", "line": 2, "issue": "B", "suggestion": "Fix", "severity": "critical"},
            {"filename": "a.py", "line": 3, "issue": "C", "suggestion": "Fix", "severity": "warning"},
        ]
        result = reviewer._deduplicate(comments)
        assert result[0]["severity"] == "critical"
        assert result[1]["severity"] == "warning"
        assert result[2]["severity"] == "suggestion"


class TestAgenticConfidenceClamping:
    def test_valid_confidence(self):
        c = ChangedFile(filename="a.py", status="modified", additions=1, deletions=0, patch="+line")
        ctx = PRContext(
            repo_name="test/repo", pr_number=1, title="T", description="",
            author="a", base_branch="main", head_branch="feat",
            files=[c], head_sha="abc123",
        )
        reviewer = AgenticReviewerAgent()
        with patch("app.agents.agentic_reviewer.llm_client") as mock_llm:
            mock_llm.complete.return_value = '{"overall_score": 8, "approved": true, "summary": "Good", "comments": [{"filename": "a.py", "line": 1, "issue": "X", "suggestion": "Y", "severity": "warning", "confidence": 0.85}]}'
            result = reviewer.run(ctx)
            assert result.comments[0].confidence == 0.85

    def test_invalid_confidence_fallback(self):
        c = ChangedFile(filename="a.py", status="modified", additions=1, deletions=0, patch="+line")
        ctx = PRContext(
            repo_name="test/repo", pr_number=1, title="T", description="",
            author="a", base_branch="main", head_branch="feat",
            files=[c], head_sha="abc123",
        )
        reviewer = AgenticReviewerAgent()
        with patch("app.agents.agentic_reviewer.llm_client") as mock_llm:
            mock_llm.complete.return_value = '{"overall_score": 8, "approved": true, "summary": "Good", "comments": [{"filename": "a.py", "line": 1, "issue": "X", "suggestion": "Y", "severity": "warning", "confidence": "not_a_number"}]}'
            result = reviewer.run(ctx)
            assert result.comments[0].confidence == 1.0

    def test_out_of_range_confidence_clamped(self):
        c = ChangedFile(filename="a.py", status="modified", additions=1, deletions=0, patch="+line")
        ctx = PRContext(
            repo_name="test/repo", pr_number=1, title="T", description="",
            author="a", base_branch="main", head_branch="feat",
            files=[c], head_sha="abc123",
        )
        reviewer = AgenticReviewerAgent()
        with patch("app.agents.agentic_reviewer.llm_client") as mock_llm:
            mock_llm.complete.return_value = '{"overall_score": 8, "approved": true, "summary": "Good", "comments": [{"filename": "a.py", "line": 1, "issue": "X", "suggestion": "Y", "severity": "warning", "confidence": 2.5}]}'
            result = reviewer.run(ctx)
            assert result.comments[0].confidence == 1.0

        with patch("app.agents.agentic_reviewer.llm_client") as mock_llm:
            mock_llm.complete.return_value = '{"overall_score": 8, "approved": true, "summary": "Good", "comments": [{"filename": "a.py", "line": 1, "issue": "X", "suggestion": "Y", "severity": "warning", "confidence": -0.5}]}'
            result = reviewer.run(ctx)
            assert result.comments[0].confidence == 0.0


class TestAgenticMalformedComments:
    def test_missing_required_fields_skipped(self):
        c = ChangedFile(filename="a.py", status="modified", additions=1, deletions=0, patch="+line")
        ctx = PRContext(
            repo_name="test/repo", pr_number=1, title="T", description="",
            author="a", base_branch="main", head_branch="feat",
            files=[c], head_sha="abc123",
        )
        reviewer = AgenticReviewerAgent()
        with patch("app.agents.agentic_reviewer.llm_client") as mock_llm:
            mock_llm.complete.return_value = '{"overall_score": 8, "approved": true, "summary": "Good", "comments": [{"filename": "a.py"}]}'
            result = reviewer.run(ctx)
            assert len(result.comments) == 0


class TestAgenticReviewPassLogic:
    def test_all_passes_fail_returns_default(self):
        c = ChangedFile(filename="a.py", status="modified", additions=1, deletions=0, patch="+line")
        ctx = PRContext(
            repo_name="test/repo", pr_number=1, title="T", description="",
            author="a", base_branch="main", head_branch="feat",
            files=[c], head_sha="abc123",
        )
        reviewer = AgenticReviewerAgent()
        with patch("app.agents.agentic_reviewer.llm_client") as mock_llm:
            mock_llm.complete.side_effect = Exception("API down")
            result = reviewer.run(ctx)
            assert result.overall_score == 5
            assert result.approved is False
            assert len(result.comments) == 0

    def test_pass_failure_doesnt_block_others(self):
        c = ChangedFile(filename="a.py", status="modified", additions=1, deletions=0, patch="+line")
        ctx = PRContext(
            repo_name="test/repo", pr_number=1, title="T", description="",
            author="a", base_branch="main", head_branch="feat",
            files=[c], head_sha="abc123",
        )
        reviewer = AgenticReviewerAgent()
        responses = [
            Exception("fail"),
            '{"overall_score": 7, "approved": true, "summary": "Ok", "comments": []}',
            '{"overall_score": 9, "approved": true, "summary": "Great", "comments": []}',
        ]
        with patch("app.agents.agentic_reviewer.llm_client") as mock_llm:
            mock_llm.complete.side_effect = responses
            result = reviewer.run(ctx)
            assert result.overall_score == 7

    def test_critical_comment_blocks_approval(self):
        c = ChangedFile(filename="a.py", status="modified", additions=1, deletions=0, patch="+line")
        ctx = PRContext(
            repo_name="test/repo", pr_number=1, title="T", description="",
            author="a", base_branch="main", head_branch="feat",
            files=[c], head_sha="abc123",
        )
        reviewer = AgenticReviewerAgent()
        response = '{"overall_score": 8, "approved": true, "summary": "Good", "comments": [{"filename": "a.py", "line": 1, "issue": "X", "suggestion": "Y", "severity": "critical", "confidence": 1.0}]}'
        with patch("app.agents.agentic_reviewer.llm_client") as mock_llm:
            mock_llm.complete.return_value = response
            result = reviewer.run(ctx)
            assert result.approved is False
