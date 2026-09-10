# PR Review Agent

A production-style multi-agent system that automatically reviews GitHub Pull Requests using AI. When a developer opens a PR, the system fetches the diff along with full repository context, runs a multi-pass security/bug/performance analysis via Llama 3.3-70b, evaluates the review quality, and posts structured feedback back to GitHub — all without human involvement.

Built with FastAPI, Groq, SQLAlchemy, ChromaDB, PyGithub, Celery, and Redis.

## How It Works

```
GitHub PR Opened
        │
        ▼
POST /webhook/github          ← FastAPI verifies HMAC-SHA256 signature
        │                       Returns 202 immediately
        ▼
   Orchestrator                ← Background task, idempotent, retries with backoff
        │
        ├── Idempotency check         ← Skip if same HEAD SHA already reviewed
        │
        ├── Stage 1: FetcherAgent
        │         GitHub API → PR metadata + file diffs + repo context
        │         ChromaDB RAG → retrieves similar past code chunks → PRContext
        │
        ├── Stage 2: ReviewerAgent (or AgenticReviewerAgent)
        │         ┌─ Security Analysis (OWASP / CWE checklist)
        │         ├─ Bug Detection & Code Quality
        │         └─ Performance & Best Practices
        │         PRContext → Groq (Llama 3.3-70b) → ReviewResult
        │         LLM fallback: Groq → Gemini if primary fails
        │
        ├── Stage 3: EvaluatorAgent
        │         ReviewResult × PRContext → hallucination rate, coverage, quality score
        │
        ├── Stage 4: PosterAgent
        │         ReviewResult → GitHub PR review (inline comments + summary)
        │
        └── Stage 5: Database
                  Save review + evaluation metrics → SQLite / PostgreSQL
```

The developer sees a structured review with an overall score (1–10), inline comments on specific lines with confidence ratings, severity classifications (critical / warning / suggestion), and an approve or request-changes verdict.

## Features

| Feature | Description |
|---------|-------------|
| **Multi-pass agentic review** | Security, bugs, and performance analyzed in separate passes with deduplication |
| **Confidence scores** | Every inline comment includes a 0–100% confidence rating |
| **Hallucination detection** | Evaluator cross-references every comment against actual diff lines |
| **Chunked review** | Large PRs (>80k chars) are automatically split into file chunks, reviewed separately, results merged |
| **RAG codebase awareness** | Full repo indexed into ChromaDB with AST-based chunking; similar code retrieved before every review |
| **Multi-language chunking** | Python (AST), JS/TS/JSX/TSX/Vue (function/class), Go (func/struct), Rust (fn/impl/enum) |
| **LLM fallback** | Groq primary, Gemini automatic fallback if primary fails |
| **Incremental RAG** | Only changed files are re-indexed on subsequent runs |
| **Idempotency** | Same PR HEAD SHA is never reviewed twice |
| **Exponential backoff** | Retries with jitter (5s → 10s → 20s, capped at 60s) |
| **HMAC-SHA256 verification** | Every webhook request signed by GitHub, verified server-side |
| **Repo-aware context** | README, file structure, languages, and recent merged PRs fetched before review |
| **PostgreSQL support** | Swap `DATABASE_URL` for production-scale deployments |
| **Redis/Celery** | Optional durable job queue for horizontal scaling |
| **Structured logging** | JSON logs with request context via structlog |
| **Self-PR detection** | Switches from APPROVE to COMMENT when bot authored the PR (avoids GitHub 422) |
| **Graceful degradation** | If inline comments fail, falls back to posting summary only |

## Agent Design

Each agent has one responsibility and no knowledge of the others. They are independently testable and replaceable.

| Agent | Responsibility |
|-------|---------------|
| **FetcherAgent** | Calls GitHub API, builds PRContext with files, metadata, and full repository context — README, file structure, languages, recent merged PRs. Triggers RAG ingestion and retrieval. |
| **ReviewerAgent** | Builds prompt with repo context + RAG context, calls Groq/Gemini, parses JSON response into ReviewResult. Supports chunked review for large PRs. |
| **AgenticReviewerAgent** | Multi-pass reviewer — runs security, bug, and performance analysis as separate LLM calls, deduplicates comments across passes, keeps highest severity and confidence. |
| **EvaluatorAgent** | Validates comments against actual diff, computes hallucination rate, coverage rate, quality score, and average confidence. |
| **PosterAgent** | Formats ReviewResult as Markdown, posts to GitHub PR. Detects self-authored PRs and switches event type to avoid GitHub 422. |

Design principles:

- **Single responsibility** — one agent, one job
- **Fail loudly** — exceptions are logged and re-raised, never swallowed silently
- **Graceful degradation** — fallbacks ensure partial success over total failure
- **Stateless** — agents take input, return output, hold no internal state

## RAG — Context Engine

The system uses Retrieval-Augmented Generation to give the AI reviewer knowledge of the full codebase, not just the changed files.

```
Repository
     │
     ▼
CodebaseIngestor
     │
     ├── Fetch all indexable files from GitHub
     │
     ├── Language-aware chunking:
     │       Python   → AST parsing (FunctionDef, AsyncFunctionDef, ClassDef)
     │       JS/TS    → Regex-based function/class boundary detection
     │       Go       → func / type struct / type interface detection
     │       Rust     → fn / struct / impl / enum / trait detection
     │       Other    → 60-line windows with 10-line overlap
     │
     ├── Embed chunks → Gemini embedding-2 (batch with retry + single fallback)
     │
     └── Store in ChromaDB (persistent, one collection per repo)
              │
              ▼
        On every PR review:
        CodebaseRetriever → embed PR diff → query ChromaDB → top-K similar chunks
              │
              ▼
        Injected into reviewer prompt as "Relevant codebase context"
```

### Why AST chunking matters

Character-based or line-based splitting cuts functions in half. The AI then sees broken, unrunnable code and cannot reason about it properly. AST-based chunking guarantees every chunk is a complete, syntactically valid unit — a whole function or a whole class.

```python
# Character split (bad) — cuts mid-function
def get_user(user_id):
    user = db.query(User).fi   ← truncated here

# AST split (good) — always a complete unit
def get_user(user_id):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404)
    return user
```

### Incremental indexing

On subsequent ingestion runs, the system computes an MD5 hash of each file's content and compares it against stored hashes. Only changed or new files are re-indexed, saving embedding API calls and time.

### Embedding reliability

The Gemini batch embed API occasionally returns fewer embeddings than texts sent. The system handles this with a three-layer strategy:

1. Retry batch embed up to 3 times
2. Fall back to one-by-one single embedding calls
3. Abort and skip the file if all calls fail (prevents corrupt index)

## Repo-Aware Context

Before reviewing any PR, the FetcherAgent gathers full context about the repository:

- **README** — what the project does and how it is structured
- **File structure** — top-level directories and files
- **Languages** — all programming languages used in the codebase
- **Recent merged PRs** — what kind of work this team ships

This context is passed to the ReviewerAgent so the AI understands the codebase before reading the diff. Reviews reference the specific repository, its tech stack, and its patterns — not just the isolated code change.

## Evaluation Layer

The EvaluatorAgent automatically measures AI review quality without human involvement.

### Hallucination Rate

The AI occasionally comments on lines that do not exist in the diff. Every comment's line number is cross-referenced against the actual diff. Comments on non-existent lines are flagged as hallucinations.

```
Hallucination Rate = hallucinated comments / total comments × 100
```

### Coverage Rate

What percentage of changed files received at least one comment.

```
Coverage Rate = files with comments / total files changed × 100
```

### Quality Score

A composite score from 0 to 100.

```
Quality Score = 100 − (hallucination rate × 0.5) + (coverage rate × 0.1)
                + (avg confidence − 0.5) × 10
                clamped between 0 and 100
```

| Score | Meaning |
|-------|---------|
| 90–100 | Excellent — AI is accurate and thorough |
| 70–90 | Good — minor hallucination or coverage gaps |
| 50–70 | Fair — prompt tuning recommended |
| Below 50 | Poor — significant hallucination problem |

## Multi-Pass Agentic Review

When `AGENTIC_MODE=true`, the system runs three separate LLM passes instead of one:

| Pass | Focus | Ignores |
|------|-------|---------|
| **Security Analysis** | Injection, auth flaws, secrets, SSRF, XSS, insecure deps | Style, performance |
| **Bug Detection & Code Quality** | Logic errors, race conditions, resource leaks, dead code | Security (handled by pass 1) |
| **Performance & Best Practices** | N+1 queries, missing caches, blocking I/O, architecture | Security |

Comments are deduplicated across passes by `(filename, line, issue prefix)`. When two passes find the same issue, the higher-severity and higher-confidence version is kept.

## LLM Fallback Chain

If the primary LLM (Groq) fails — rate limit, timeout, outage — the system automatically retries with Gemini:

```
Groq (Llama 3.3-70b)  →  Gemini 2.0 Flash
     Primary                Fallback
```

The fallback is transparent to the rest of the pipeline. The same prompt and JSON parsing work with both providers.

## Tech Stack

| Technology | Purpose |
|-----------|---------|
| Python 3.11 | Language |
| FastAPI | Web framework — async, fast, auto-docs |
| Uvicorn | ASGI server |
| Groq API | LLM inference — fastest Llama 3 inference available |
| Llama 3.3-70b | AI model — open weight, reliable structured output |
| Gemini 2.0 Flash | LLM fallback + embedding model (embedding-2) |
| ChromaDB | Vector database — persistent codebase index, one collection per repo |
| BM25 (rank_bm25) | Keyword search — hybrid with vector search for better retrieval |
| Celery + Redis | Optional job queue for durable background processing |
| PyGithub | GitHub API integration — handles auth, pagination, rate limits |
| SQLAlchemy | ORM — database portability, no raw SQL |
| SQLite | Default database — zero infrastructure, file-based |
| PostgreSQL | Production database — swap one env var |
| Pydantic | Data validation — validates AI response structure |
| structlog | Structured JSON logging with request context |
| PyGithub | GitHub API — auth, PR ops, review posting |
| Docker | Containerized deployment with health checks |
| GitHub Actions | CI — runs full test suite on push/PR |

## Project Structure

```
pr-review-agent/
├── app/
│   ├── main.py                 # FastAPI app, webhook endpoint, middleware
│   ├── config.py               # Settings loaded from .env (pydantic-settings)
│   ├── celery_app.py           # Celery configuration and app
│   ├── tasks.py                # Celery tasks (review_pr, ingest_repo)
│   ├── logging_config.py       # Structured logging setup (structlog)
│   ├── agents/
│   │   ├── fetcher.py          # Agent 1: fetch PR + repo context + trigger RAG
│   │   ├── reviewer.py         # Agent 2: review with Groq/Gemini + chunked review
│   │   ├── agentic_reviewer.py # Agent 2b: multi-pass security/bugs/performance
│   │   └── poster.py           # Agent 4: post review to GitHub PR
│   ├── core/
│   │   ├── orchestrator.py     # Pipeline controller: idempotency, retry, backoff
│   │   ├── evaluator.py        # Agent 3: evaluate review quality + confidence
│   │   ├── prompts.py          # System prompt with OWASP/CWE checklist
│   │   ├── schemas.py          # Pydantic models and dataclasses
│   │   └── utils.py            # Diff parser, collection naming
│   ├── llm/
│   │   └── __init__.py         # LLM client with Groq → Gemini fallback
│   ├── rag/
│   │   ├── ingestor.py         # Chunking, embedding, ChromaDB storage, incremental
│   │   ├── chunkers.py         # Language-aware chunkers (JS/TS, Go, Rust)
│   │   └── retriever.py        # Query ChromaDB + BM25, return top-K relevant chunks
│   └── db/
│       ├── database.py         # SQLAlchemy engine and session factory
│       ├── models.py           # ORM models — PRReview, ReviewComment, EvaluationMetrics
│       └── crud.py             # Database read/write + idempotency check
├── tests/
│   ├── conftest.py             # Shared fixtures
│   ├── test_webhook.py         # Webhook verification and routing tests
│   ├── test_agents.py          # Agent unit tests with mocked APIs
│   ├── test_evaluator.py       # Evaluator tests
│   ├── test_db.py              # Database tests
│   ├── test_concurrency.py     # Concurrent request tests
│   ├── test_poster_filtering.py# Hallucination filtering tests
│   └── test_truncation.py      # Diff truncation tests
├── .github/
│   └── workflows/
│       └── ci.yml              # GitHub Actions CI pipeline
├── run.py                      # Manual pipeline runner — test any PR instantly
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
├── .env.example
└── README.md
```

## Setup

### Prerequisites

- Python 3.11+
- Groq API key — https://console.groq.com
- Google Gemini API key — https://aistudio.google.com (for embeddings + fallback)
- GitHub Personal Access Token with `repo` scope
- A GitHub repository with webhook access

### Installation

```bash
git clone https://github.com/NeelamTharunKumar/pr-review-agent
cd pr-review-agent

python -m venv venv
source venv/bin/activate        # Mac / Linux
venv\Scripts\activate           # Windows

pip install -r requirements.txt

cp .env.example .env
```

### Environment Variables

```env
# Required
GITHUB_TOKEN=ghp_your_token_here
GITHUB_WEBHOOK_SECRET=your_webhook_secret_here
GROQ_API_KEY=gsk_your_groq_key_here
GEMINI_API_KEY=your_gemini_key_here

# Database (SQLite default, swap for PostgreSQL in production)
DATABASE_URL=sqlite:///./reviews.db

# Review behavior
AGENTIC_MODE=false              # true = multi-pass security/bugs/performance
MAX_DIFF_LINES_PER_FILE=1000

# LLM provider chain
LLM_PRIMARY=groq
LLM_FALLBACK=gemini

# Job queue (optional)
USE_CELERY=false
REDIS_URL=redis://localhost:6379/0

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## Running the System

### Option 1 — Docker (recommended)

```bash
docker compose up --build
```

This starts the FastAPI server, Redis, and Celery worker. API available at `http://localhost:8000`.

### Option 2 — Manual testing

Test the full pipeline on any PR instantly:

```bash
python run.py 42 --repo owner/repo
```

### Option 3 — Webhook server

```bash
uvicorn app.main:app --reload --port 8000
```

API available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

Expose to the internet for automatic webhook triggering:

```bash
ngrok http 8000
```

### Webhook Setup

Go to your GitHub repository → Settings → Webhooks → Add webhook

| Field | Value |
|-------|-------|
| Payload URL | `https://your-ngrok-url/webhook/github` |
| Content type | `application/json` |
| Secret | Your `GITHUB_WEBHOOK_SECRET` value |
| Events | Pull requests |

Open a PR on the repository — the system reviews it automatically.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Server health check + Celery status |
| `GET` | `/metrics` | AI quality metrics across all reviews |
| `GET` | `/reviews/{owner}/{repo}` | List reviews for a repository |
| `POST` | `/ingest/{owner}/{repo}` | Trigger RAG indexing for a repo |
| `POST` | `/webhook/github` | GitHub webhook receiver |

### Sample `/metrics` Response

```json
{
  "system_stats": {
    "total_reviews": 5,
    "approved": 3,
    "rejected": 2,
    "critical_comments_found": 8,
    "hallucinated_comments": 1,
    "valid_comments": 12
  },
  "ai_quality": {
    "total_reviews_evaluated": 5,
    "average_quality_score": 94.5,
    "average_hallucination_rate": 3.2,
    "average_coverage_rate": 87.0,
    "total_comments_made": 13,
    "total_hallucinations_detected": 1
  }
}
```

## Security

- **HMAC-SHA256 verification** — every webhook request is signed by GitHub and verified server-side. Requests with invalid signatures are rejected with 401.
- **Timing-safe comparison** — `hmac.compare_digest()` prevents timing attacks on signature verification.
- **Secret management** — all API keys stored in `.env`, never committed to version control.
- **Non-root Docker** — container runs as `appuser`, not root.
- **OWASP/CWE checklist** — system prompt includes SQL injection, XSS, SSRF, hardcoded secrets, auth flaws, and 8 more vulnerability categories.

## Tests

```bash
pytest tests -v
```

45 tests covering webhook verification, agent behavior, evaluator logic, hallucination filtering, truncation handling, database operations, and concurrency.

## Key Learnings

- **Context is everything in RAG** — AST chunking made a noticeable difference in review quality compared to line-based splitting.
- **Building evaluation early helps iterate faster** — the hallucination detector caught issues that would have gone unnoticed.
- **Production AI needs strong error handling and fallbacks** — the LLM fallback chain has already saved reviews during Groq outages.
- **Multi-pass review finds what single-pass misses** — security-specific pass catches vulnerabilities that a general review overlooks.

## Future Improvements

- **Checkpoint-based retries** — resume pipeline from last successful stage instead of restarting
- **Multi-model consensus** — run two LLMs independently, merge results to reduce false positives
- **Per-author profiles** — track developer patterns over time and personalize feedback
- **User feedback collection** — thumbs up/down on AI comments to improve over time
- **MCP compatibility** — wrap agents as MCP tools for use with Claude and other MCP-compatible hosts

---

Built by **Neelam Tharun Kumar**

Production-style AI engineering project demonstrating multi-agent orchestration, AST-based RAG context engine, repo-aware LLM integration, structured output parsing, and automated evaluation of AI review quality.
