# Slice 0: skeleton

Date: 2026-10-05. Branch `claude/funny-cori-evrx1v`.

## What was built

- A uv project (`pyproject.toml`, `uv.lock`, `.python-version` = 3.12) with the `coach` package under `src/`, a `coach` console script, and `anthropic 1.11`, `httpx 0.28`, `pydantic 2.13` as runtime dependencies. Dev group: pytest, ruff, pre-commit.
- `coach.settings`: the only module that reads environment variables. `Secret` redacts itself in `repr` and `str`; the Anthropic key comes from `COACH_ANTHROPIC_API_KEY` with `ANTHROPIC_API_KEY` as the fallback and the error names both; the Hevy credential is either the `env` route (`HEVY_API_KEY` set) or the `proxy` route (placeholder `proxy-injected` sent, header replaced by the platform proxy). `COACH_MODEL` overrides the pinned default `claude-haiku-4-5-20251001`.
- `coach.credentials` and `coach check-credentials`: one `GET /v1/models` through the SDK with `api_key=` passed explicitly and `max_retries=0`, one `GET /v1/workouts/count` to Hevy, printing the HTTP status of each and the Hevy route. A 401 on the proxy route says the proxy is not injecting the header; a 401 on the env route says the key was rejected. Nothing else is printed.
- Pre-commit with `ruff-check`, `ruff-format` (astral-sh/ruff-pre-commit v0.16.10) and `gitleaks` (gitleaks/gitleaks v8.30.1), installed in this checkout so the secret scan runs before every commit.
- GitHub Actions (`.github/workflows/ci.yml`): `uv sync --locked`, `ruff check`, `ruff format --check`, `pytest`, and a gitleaks scan of the whole history using the pinned 8.30.1 Linux binary verified against the SHA-256 from the release's checksums file. No API calls.
- `.gitignore` for `private/`, `out/`, `.env*` (with `.env.example` allowed back in), `.env.example` holding the two variable names and no values, MIT `LICENSE`, `README.md` with two paragraphs and a status line, `docs/later.md`.
- Tests: one trivial import test, eight on settings, nine on the credential check using `httpx.MockTransport` and a hand-written fake of the SDK client. No test touches the network or needs a key.

## Credential check, documented

Command: `uv run coach check-credentials`. Requests: `GET https://api.anthropic.com/v1/models?limit=1` via `client.models.with_raw_response.list(limit=1)` (the SDK adds `x-api-key` and `anthropic-version`; endpoint per platform.claude.com/docs/en/api/models/list), and `GET https://api.hevyapp.com/v1/workouts/count` with the `api-key` header (Hevy OpenAPI). Exit code 0 only when both return 200.

Result in this session on 2026-10-05:

```
anthropic  200  GET /v1/models
hevy       200  route=proxy
```

The Hevy route was `proxy`: `HEVY_API_KEY` is not set, the placeholder was sent, and the platform proxy supplied the real header. The Anthropic key came from `COACH_ANTHROPIC_API_KEY`.

## Decisions and rejected alternatives

- **SDK for the Anthropic check, httpx for Hevy.** The Anthropic call goes through the official SDK so the project never mixes raw HTTP and SDK calls to the same API; `with_raw_response` gives the status code. Rejected: a raw `httpx` GET to `api.anthropic.com`, which would have been shorter but set a precedent the review loop must not follow.
- **`max_retries=0` on the check client.** The SDK retries 429 and 5xx twice by default (Python SDK page). A credential check should report the first answer. The review client in slice 3 keeps the default.
- **`Secret` as a class, not a `str` subclass.** A `str` subclass still formats itself in f-strings. Rejected: `pydantic.SecretStr`, which does the same job but would make a Pydantic import the reason the settings module exists.
- **gitleaks over detect-secrets.** gitleaks has an official pre-commit hook, a single pinned binary for CI, and `--redact` so a finding never prints the value. Rejected: `gitleaks/gitleaks-action`, which requires a licence key for organisation repositories; downloading the release binary with a checksum avoids that and keeps CI free of third-party actions beyond checkout and setup-uv.
- **`src/` layout.** The spec said `coach/`; the package is still `coach`, under `src/`, because uv's build backend defaults to it and it stops tests importing the working copy by accident.
- **Repository-wide gitleaks history scan in CI, staged-only scan in the hook.** The hook's documented entry scans staged changes, which is the right pre-commit cost; CI scans every commit with `fetch-depth: 0` so nothing slips through a hook that was not installed.
- **Pinned action majors** `actions/checkout@v7` and `astral-sh/setup-uv@v10.2.0` (tags read with `git ls-remote` on 2026-10-05; setup-uv publishes no floating `v10` tag, which failed the first CI run; Secondary).

## How to run it

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run pre-commit install           # once per checkout
uv run pre-commit run --all-files
uv run coach check-credentials
```

## What it does not do yet

No Hevy client, no pagination, no raw page store, no figures, no model call beyond listing models. The LICENSE names "the coach-app authors" as copyright holder pending your name. The first CI run failed on an unresolvable `astral-sh/setup-uv@v10` pin; the second run, with the exact tag, is reported in the slice 0 message.

## Three questions an interviewer might ask

1. Why send a placeholder header at all on the proxy route instead of omitting the header? Because Hevy's OpenAPI marks `api-key` as required on every operation; sending a visible placeholder makes the request shape identical on both routes, and a 401 then has exactly one meaning per route, which the error message states.
2. Why is the credential check allowed to call two live APIs when the rule is "no network in tests"? The check is a command, not a test. Its tests use `httpx.MockTransport` and a fake client; the live call happens only when you run the command, and the brief asks for the two status codes before the first model call.
3. What does `max_retries=0` protect against here, and why not everywhere? A 401 or a 429 should surface immediately in a credential check so the output means something. In the review loop, transport retries on 429 and 5xx are the correct default, and they are distinct from the content retries the loop deliberately never does.
