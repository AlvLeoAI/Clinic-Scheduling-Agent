# Local development, demonstrations and recovery

Requires Python 3.12, PostgreSQL 16 through local Docker Compose, and uv or an isolated pip environment. Only synthetic data is supported. Legacy executables, voice dependencies and unverified fixtures are excluded from this candidate. This document describes the existing application; R1A does not authorize running it.

## Bootstrap after separate R1B authorization

Use a disposable verification copy. Set a unique CLINIC_VERIFY_PROJECT value and select a free loopback POSTGRES_PORT different from the original instance. Update both URLs and the fresh password in the new private .env consistently. Clear any inherited DATABASE_URL, TEST_DATABASE_URL, POSTGRES_*, OPENAI_* and ELEVENLABS_* environment overrides before loading this new configuration. Confirm no container/volume already belongs to this new project before creating it. Never use the unqualified Compose commands against the original fixed project name.

Obtain the pinned PostgreSQL image only when needed on a new machine; the local M6 reproduction uses an already cached image. Dependencies are version-pinned in the foundation lock. Package/image acquisition is distinct from a paid model call.

```bash
uv venv --python python3 .venv
uv pip sync --python .venv/bin/python requirements-foundation.lock
cp -n .env.example .env
chmod 600 .env
# Privately replace <local_demo_password> consistently with a new local-only password.
# Never add vendor keys. Keep ENABLE_LIVE_OPENAI=false.
docker pull postgres:16-alpine@sha256:4e6e670bb069649261c9c18031f0aded7bb249a5b6664ddec29c013a89310d50
: "${CLINIC_VERIFY_PROJECT:?Set a unique verification-only project name first}"
docker compose -p "$CLINIC_VERIFY_PROJECT" up -d --wait postgres
.venv/bin/alembic upgrade head
.venv/bin/python -m scripts.seed
.venv/bin/python -m scripts.seed
.venv/bin/alembic check
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

The source template defaults to loopback port 15432 and a fixed Compose project name; those defaults must be replaced/overridden for verification to avoid sharing the original instance. Initialization creates separate `clinic_scheduling_dev` and `clinic_scheduling_test`. For another isolated project, choose a free POSTGRES_PORT and update both private URLs consistently; use a distinct `docker compose -p <project>` name. Do not reuse/remove another project's volume. Initialization only runs on a fresh volume. Seed upserts fixed artificial catalog/schedules and never resets appointments.

Foundation/availability/booking work without vendor keys. Default chat provider is disabled and returns safe uncertainty until separately authorized/configured; the offline CLI supplies its own fake provider and never constructs a live provider. No real model ID/capability is claimed.

## Offline CLI

```bash
.venv/bin/python -m cli --synthetic-only --scripted
.venv/bin/python -m cli --synthetic-only
```

Both use only TEST_DATABASE_URL, guarded to local `clinic_demo` / `clinic_scheduling_test`, and fake clock 2030-01-07 15:00 UTC. The CLI embeds the existing FastAPI application through an in-process HTTP test transport. It is a local demonstration, not a deployed server or natural-language model benchmark. Normal text reaches `/chat/messages`; `confirm UUID` bypasses chat and posts directly to confirmation. Supported fake grammar is catalog; availability DATE PRACTITIONER_UUID TYPE_UUID; propose DATE HH:MM PRACTITIONER_UUID TYPE_UUID. Type quit to leave.

Interactive state defaults to ignored `.local/cli_state.json`: bearer, original confirmation keys and pending client-message payload are private, mode 0600, atomically saved before requests and bound to the demo backend. A state file with wrong permissions, symlink or mismatched scope is refused. Reuse the same state to resume; an expired owning bearer is not silently replaced. Use a separate new state path for a new session, never to recover an uncertain old confirmation.

On uncertain chat, use retry-chat to retain the original UUID/content. On uncertain confirmation, repeat `confirm UUID` with the same private state. The key remains stable across retries/restart. A 201 response is followed by authenticated appointment retrieval before CONFIRMED is displayed. Expired, superseded or conflicted outcomes are fetched from the proposal endpoint; no conversational “yes” is consent. Changing booking details requires a new proposal. Session lifetime is 24 hours without sliding renewal; recovery beyond owner expiry is not implemented.

Scripted mode uses a fresh temporary state/session, injects one response loss after a real commit, independently reads PostgreSQL, reloads state in a fresh app/pool and recovers/replays with the same key. It then deletes only its own ephemeral fixture rows. It does not use or delete an interactive session.

## Concurrency and safe cleanup

```bash
.venv/bin/python scripts/demo_concurrency.py --synthetic-only
```

Requires an empty appointment table in the designated test DB. If not empty, it refuses rather than reset. Run it before persistent interactive bookings, or use a separate synthetic test instance. It creates two sessions/clients/pools and overlapping 60-/30-minute proposals. A demo-only method wrapper synchronizes both after preflight so PostgreSQL produces a real exclusion race. The 60-minute request wins deterministically; the loser receives SLOT_TAKEN. A third pool verifies one committed row; both keys replay identically, then availability is independently checked and displayed for the loser.

The script validates URL/role/host/DB and matching engine before operations, and rechecks the cleanup target. It deletes only newly owned fixture IDs, never globally resets tables. Displayed booking evidence is captured before ephemeral cleanup; final own-row count is zero. This is a controlled concurrency proof, not a fairness/load benchmark.

Run tests/demos sequentially. Stop only the current project's PostgreSQL with `docker compose -p "$CLINIC_VERIFY_PROJECT" stop postgres`. Never use a broad `down -v` to repair development data. [M6 reproduction evidence](evidence/M6_report.md) distinguishes isolated source-copy setup from fresh-clone testing and hosted CI.

The commands above are documentation, not R1A execution evidence. No candidate environment, server, database, session or CLI state was created during R1A.
