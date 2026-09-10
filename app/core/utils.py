import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

SKIP_PATTERNS = [
    "package-lock.json",
    "yarn.lock",
    "poetry.lock",
    ".min.js",
    ".min.css",
    "requirements.txt",
    "Pipfile.lock",
]


def safe_collection_name(repo_name: str) -> str:
    return repo_name.replace("/", "__").replace("-", "_")


def parse_json_response(raw_response: str) -> dict[str, Any]:
    """Parse LLM JSON response, stripping markdown code fences."""
    cleaned = raw_response.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    if cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e}")
        logger.error(f"Raw response (first 500 chars): {raw_response[:500]}")
        return {
            "overall_score": 5,
            "approved": False,
            "summary": "Review could not be parsed.",
            "comments": [],
        }


def split_files_into_chunks(files: list, chunk_size: int = 80000) -> list[list]:
    """Split files into chunks based on total patch size."""
    chunks: list[list] = []
    current_chunk: list = []
    current_size = 0

    for f in files:
        patch_size = len(f.patch) if f.patch else 0
        if current_size + patch_size > chunk_size and current_chunk:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(f)
        current_size += patch_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks if chunks else [files]


def parse_diff_new_file_lines(patch: str) -> set[int]:
    """Return new-file line numbers present in a unified diff patch."""
    if not patch:
        return set()

    lines_in_new_file: set[int] = set()
    new_line = 1
    saw_hunk = False

    for raw in patch.split("\n"):
        if raw.startswith("@@"):
            match = re.search(r"\+(\d+)", raw)
            if match:
                new_line = int(match.group(1))
                saw_hunk = True
            continue

        if raw.startswith("\\"):
            continue

        if raw.startswith("+"):
            lines_in_new_file.add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            continue
        else:
            if saw_hunk or raw:
                lines_in_new_file.add(new_line)
                new_line += 1

    if not saw_hunk and not lines_in_new_file:
        count = len([ln for ln in patch.split("\n") if ln])
        return set(range(1, count + 1))

    return lines_in_new_file
