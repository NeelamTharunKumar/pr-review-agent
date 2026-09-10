import pytest
from app.core.schemas import (
    ChangedFile,
    PRContext,
    RepoContext,
    ReviewResult,
    ReviewComment,
)


class TestChangedFile:
    def test_create(self):
        f = ChangedFile(filename="a.py", status="modified", additions=5, deletions=2, patch="@@ +1 @@\n+line")
        assert f.filename == "a.py"
        assert f.additions == 5
        assert f.deletions == 2

    def test_defaults(self):
        f = ChangedFile(filename="b.py", status="added", additions=0, deletions=0, patch="")
        assert f.patch == ""


class TestRepoContext:
    def test_create(self):
        rc = RepoContext(
            name="org/repo",
            description="Test",
            primary_language="Python",
            languages="Python, JS",
            file_structure="src/\ntests/",
            readme_summary="A repo",
        )
        assert rc.name == "org/repo"
        assert rc.primary_language == "Python"

    def test_recent_prs_default(self):
        rc = RepoContext(
            name="org/repo", description="D", primary_language="Python",
            languages="Python", file_structure="src/", readme_summary="R",
        )
        assert rc.recent_pr_titles == []


class TestPRContext:
    def test_minimal(self):
        ctx = PRContext(
            repo_name="org/repo", pr_number=1, title="T", description="D",
            author="a", base_branch="main", head_branch="feat",
        )
        assert ctx.repo_name == "org/repo"
        assert ctx.files == []
        assert ctx.truncated_files == []

    def test_with_files(self):
        f = ChangedFile(filename="a.py", status="modified", additions=1, deletions=0, patch="+")
        ctx = PRContext(
            repo_name="org/repo", pr_number=1, title="T", description="D",
            author="a", base_branch="main", head_branch="feat",
            files=[f],
        )
        assert len(ctx.files) == 1


class TestReviewComment:
    def test_create(self):
        c = ReviewComment(filename="a.py", line=10, issue="Bug", suggestion="Fix", severity="critical")
        assert c.filename == "a.py"
        assert c.confidence == 1.0

    def test_with_confidence(self):
        c = ReviewComment(filename="a.py", line=10, issue="Bug", suggestion="Fix", severity="warning", confidence=0.75)
        assert c.confidence == 0.75


class TestReviewResult:
    def test_create(self):
        r = ReviewResult(overall_score=8, approved=True, summary="Good", comments=[])
        assert r.overall_score == 8
        assert r.approved is True

    def test_with_comments(self):
        c = ReviewComment(filename="a.py", line=1, issue="X", suggestion="Y", severity="warning")
        r = ReviewResult(overall_score=7, approved=False, summary="Needs work", comments=[c])
        assert len(r.comments) == 1
        assert r.comments[0].severity == "warning"
