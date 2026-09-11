from app.core.schemas import ChangedFile
from app.core.utils import (
    SKIP_PATTERNS,
    parse_diff_new_file_lines,
    parse_json_response,
    safe_collection_name,
    split_files_into_chunks,
)


class TestSafeCollectionName:
    def test_slash_replaced(self):
        assert safe_collection_name("org/repo") == "org__repo"

    def test_dash_replaced(self):
        assert safe_collection_name("my-repo") == "my_repo"

    def test_combined(self):
        assert safe_collection_name("org/my-repo") == "org__my_repo"

    def test_no_changes(self):
        assert safe_collection_name("simple") == "simple"


class TestParseJsonResponse:
    def test_valid_json(self):
        result = parse_json_response('{"overall_score": 8, "approved": true}')
        assert result["overall_score"] == 8
        assert result["approved"] is True

    def test_json_codeblock(self):
        result = parse_json_response('```json\n{"overall_score": 7}\n```')
        assert result["overall_score"] == 7

    def test_plain_codeblock(self):
        result = parse_json_response('```\n{"overall_score": 9}\n```')
        assert result["overall_score"] == 9

    def test_invalid_json_fallback(self):
        result = parse_json_response("not json at all")
        assert result["overall_score"] == 5
        assert result["approved"] is False
        assert "could not be parsed" in result["summary"]

    def test_empty_string(self):
        result = parse_json_response("")
        assert result["overall_score"] == 5

    def test_extra_whitespace(self):
        result = parse_json_response('  \n  {"overall_score": 6}  \n  ')
        assert result["overall_score"] == 6

    def test_only_start_codeblock(self):
        result = parse_json_response('```json\n{"overall_score": 10}')
        assert result["overall_score"] == 10

    def test_empty_codeblock(self):
        result = parse_json_response("```json\n```")
        assert result["overall_score"] == 5


class TestSplitFilesIntoChunks:
    def test_single_chunk(self):
        files = [
            ChangedFile(
                filename="a.py", status="modified", additions=5, deletions=0, patch="+" * 100
            )
        ]
        chunks = split_files_into_chunks(files, chunk_size=10000)
        assert len(chunks) == 1
        assert len(chunks[0]) == 1

    def test_multiple_chunks(self):
        files = [
            ChangedFile(
                filename="a.py", status="modified", additions=5, deletions=0, patch="+" * 50000
            ),
            ChangedFile(
                filename="b.py", status="modified", additions=5, deletions=0, patch="+" * 50000
            ),
            ChangedFile(
                filename="c.py", status="modified", additions=5, deletions=0, patch="+" * 50000
            ),
        ]
        chunks = split_files_into_chunks(files, chunk_size=80000)
        assert len(chunks) >= 2

    def test_empty_files(self):
        files = [
            ChangedFile(filename="a.py", status="modified", additions=0, deletions=0, patch="")
        ]
        chunks = split_files_into_chunks(files, chunk_size=80000)
        assert len(chunks) == 1

    def test_no_files_returns_single_chunk(self):
        chunks = split_files_into_chunks([], chunk_size=80000)
        assert len(chunks) == 1
        assert chunks[0] == []


class TestParseDiffNewFileLines:
    def test_simple_hunk(self):
        patch = "@@ -1,3 +1,5 @@\n context\n+new line 1\n+new line 2\n+new line 3\n context"
        lines = parse_diff_new_file_lines(patch)
        assert 2 in lines
        assert 3 in lines
        assert 4 in lines

    def test_empty_patch(self):
        assert parse_diff_new_file_lines("") == set()

    def test_none_patch(self):
        assert parse_diff_new_file_lines(None) == set()

    def test_additions_only(self):
        patch = "@@ -0,0 +1,3 @@\n+line1\n+line2\n+line3"
        lines = parse_diff_new_file_lines(patch)
        assert lines == {1, 2, 3}

    def test_no_hunk_header(self):
        patch = "+line1\n+line2\n+line3"
        lines = parse_diff_new_file_lines(patch)
        assert 1 in lines

    def test_backslash_line_skipped(self):
        patch = "@@ -1,3 +1,4 @@\n+new\n old\n+new2\n\\ No newline at end of file"
        lines = parse_diff_new_file_lines(patch)
        assert len(lines) >= 2

    def test_deletions_not_counted(self):
        patch = "@@ -1,5 +1,3 @@\n+kept\n-removed1\n-removed2\n context\n+kept2"
        lines = parse_diff_new_file_lines(patch)
        assert 1 in lines
        assert 2 in lines


class TestSkipPatterns:
    def test_skip_patterns_include_lockfiles(self):
        assert "package-lock.json" in SKIP_PATTERNS
        assert "yarn.lock" in SKIP_PATTERNS
        assert "poetry.lock" in SKIP_PATTERNS
        assert "Pipfile.lock" in SKIP_PATTERNS

    def test_skip_patterns_include_minified(self):
        assert ".min.js" in SKIP_PATTERNS
        assert ".min.css" in SKIP_PATTERNS

    def test_skip_patterns_include_requirements(self):
        assert "requirements.txt" in SKIP_PATTERNS
