import os
import re
import logging

logger = logging.getLogger(__name__)


def chunk_javascript(filepath: str, content: str) -> list[dict]:
    pattern = re.compile(
        r"(?:^|\n)"
        r"(?:export\s+)?(?:async\s+)?(?:function\s+(\w+)"
        r"|class\s+(\w+)"
        r"|const\s+(\w+)\s*=\s*(?:async\s+)?\("
        r"|const\s+(\w+)\s*=\s*(?:async\s+)?function"
        r"|export\s+default\s+(?:function|class)\s+(\w+))",
        re.MULTILINE,
    )

    lines = content.split("\n")
    boundaries = [0]

    for match in pattern.finditer(content):
        pos = match.start()
        line_num = content[:pos].count("\n")
        boundaries.append(line_num)

    boundaries.append(len(lines))
    boundaries = sorted(set(boundaries))

    chunks = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        chunk_text = "\n".join(lines[start:end])

        if len(chunk_text.strip()) < 30:
            continue

        name_match = pattern.search(chunk_text)
        name = filepath
        if name_match:
            for g in name_match.groups():
                if g:
                    name = g
                    break

        chunks.append({
            "text": chunk_text,
            "filepath": filepath,
            "start_line": start + 1,
            "end_line": end,
            "type": "function/class",
            "name": name,
        })

    if not chunks and len(content.strip()) > 0 and len(content) < 5000:
        chunks.append({
            "text": content,
            "filepath": filepath,
            "start_line": 1,
            "end_line": len(lines),
            "type": "module",
            "name": filepath,
        })

    return chunks


def chunk_go(filepath: str, content: str) -> list[dict]:
    pattern = re.compile(
        r"(?:^|\n)(func\s+(?:\(\w+\s+\*?\w+\)\s+)?(\w+)"
        r"|type\s+(\w+)\s+struct"
        r"|type\s+(\w+)\s+interface)",
        re.MULTILINE,
    )

    lines = content.split("\n")
    boundaries = [0]

    for match in pattern.finditer(content):
        pos = match.start()
        line_num = content[:pos].count("\n")
        boundaries.append(line_num)

    boundaries.append(len(lines))
    boundaries = sorted(set(boundaries))

    chunks = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        chunk_text = "\n".join(lines[start:end])

        if len(chunk_text.strip()) < 20:
            continue

        name = filepath
        name_match = pattern.search(chunk_text)
        if name_match:
            for g in name_match.groups():
                if g:
                    name = g
                    break

        chunk_type = "function"
        if "struct" in chunk_text[:100]:
            chunk_type = "struct"
        elif "interface" in chunk_text[:100]:
            chunk_type = "interface"

        chunks.append({
            "text": chunk_text,
            "filepath": filepath,
            "start_line": start + 1,
            "end_line": end,
            "type": chunk_type,
            "name": name,
        })

    if not chunks and len(content.strip()) > 0 and len(content) < 5000:
        chunks.append({
            "text": content,
            "filepath": filepath,
            "start_line": 1,
            "end_line": len(lines),
            "type": "package",
            "name": filepath,
        })

    return chunks


def chunk_rust(filepath: str, content: str) -> list[dict]:
    pattern = re.compile(
        r"(?:^|\n)(?:pub\s+)?(?:async\s+)?fn\s+(\w+)"
        r"|(?:pub\s+)?struct\s+(\w+)"
        r"|(?:pub\s+)?impl(?:\s+<[^>]+>)?\s+(\w+)"
        r"|(?:pub\s+)?enum\s+(\w+)"
        r"|trait\s+(\w+)",
        re.MULTILINE,
    )

    lines = content.split("\n")
    boundaries = [0]

    for match in pattern.finditer(content):
        pos = match.start()
        line_num = content[:pos].count("\n")
        boundaries.append(line_num)

    boundaries.append(len(lines))
    boundaries = sorted(set(boundaries))

    chunks = []
    for i in range(len(boundaries) - 1):
        start = boundaries[i]
        end = boundaries[i + 1]
        chunk_text = "\n".join(lines[start:end])

        if len(chunk_text.strip()) < 20:
            continue

        name = filepath
        name_match = pattern.search(chunk_text)
        if name_match:
            for g in name_match.groups():
                if g:
                    name = g
                    break

        chunk_type = "function"
        if "struct" in chunk_text[:100]:
            chunk_type = "struct"
        elif "impl" in chunk_text[:100]:
            chunk_type = "impl"
        elif "enum" in chunk_text[:100]:
            chunk_type = "enum"
        elif "trait" in chunk_text[:100]:
            chunk_type = "trait"

        chunks.append({
            "text": chunk_text,
            "filepath": filepath,
            "start_line": start + 1,
            "end_line": end,
            "type": chunk_type,
            "name": name,
        })

    if not chunks and len(content.strip()) > 0 and len(content) < 5000:
        chunks.append({
            "text": content,
            "filepath": filepath,
            "start_line": 1,
            "end_line": len(lines),
            "type": "module",
            "name": filepath,
        })

    return chunks


LANGUAGE_CHUNKERS = {
    ".js": chunk_javascript,
    ".jsx": chunk_javascript,
    ".ts": chunk_javascript,
    ".tsx": chunk_javascript,
    ".vue": chunk_javascript,
    ".go": chunk_go,
    ".rs": chunk_rust,
}


def chunk_file(filepath: str, content: str, python_chunker) -> list[dict]:
    ext = os.path.splitext(filepath)[1].lower()
    chunker = LANGUAGE_CHUNKERS.get(ext)
    if chunker:
        return chunker(filepath, content)
    if ext == ".py":
        return python_chunker(filepath, content)
    return _chunk_by_lines(filepath, content)


def _chunk_by_lines(filepath: str, content: str) -> list[dict]:
    lines = content.split("\n")
    chunks = []
    chunk_size = 60
    overlap = 10
    i = 0

    while i < len(lines):
        chunk_lines = lines[i : i + chunk_size]
        chunk_text = "\n".join(chunk_lines)

        if chunk_text.strip():
            chunks.append({
                "text": chunk_text,
                "filepath": filepath,
                "start_line": i + 1,
                "end_line": min(i + chunk_size, len(lines)),
                "type": "chunk",
                "name": f"{filepath}:{i + 1}",
            })

        i += chunk_size - overlap

    return chunks
