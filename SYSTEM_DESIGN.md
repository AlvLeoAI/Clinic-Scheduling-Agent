# System design

A synthetic, text-based scheduling backend with an LLM agent on top. The backend owns
scheduling rules, proposal state and booking; the model can only read and propose.
The architecture diagram is in the [README](README.md#architecture).

## Components

| Component | Responsibility |
| --- | --- |
| `cli/` | Demo client: private session and idempotency state, HTTP calls, verified display. `confirm <id>` goes straight to the confirm endpoint, never through chat. |
| `app/api/`, `app/schemas/` | Versioned `/api/v1` contracts, bearer-derived ownership, validated inputs, sanitized error envelopes with trace IDs. |
| `app/core/admission.py` | Rejects HTTP bodies over 64 KiB before routing or JSON parsing. |
| `app/domain/`, `app/services/scheduling.py` | Deterministic time and interval rules; availability computed from PostgreSQL. |
| `app/services/booking.py` | Immutable proposals, one-way status transitions, confirmation with revalidation, conflict mapping, durable idempotent results. |
| `app/services/chat.py`, `conversation.py`, `intent.py` | Agent loop, durable turn journal, message deduplication, per-session lease and fence, stale-intent ordering. |
| `app/agent/` | Tool registry and schemas, provider registry (`demo`, `openai`), Responses API adapter, scripted demo provider, context selection, `ReplyPlan` and template renderer. |
| `app/db/`, `alembic/` | Ten-table schema with ownership, uniqueness and exclusion constraints; synthetic catalog seed. |
| `evaluations/` | Independent interval oracle and separate raw, backend and visible graders; versioned contracts. |
| `app/services/retention.py` | Purges stored chat text (conversation items, request hashes, stored replies) of sessions expired beyond `CHAT_RETENTION_DAYS`; never touches bookings. |
| `scripts/` | Guarded demo setup and cleanup, runtime database role, concurrency demo, chat retention purge, current-tree secret check, doc checks. |
| `ui/` | Streamlit demo client. Reads and proposes through the API; books only through the confirm endpoint with one idempotency key per proposal. No database access. |
| `Dockerfile`, `ui/Dockerfile`, `compose.demo.yaml` | Pinned non-root API and UI images, and a one-command local stack with a one-off migrate+seed step. |
| `infra/terraform/`, `.github/workflows/deploy.yml` | AWS sandbox: bootstrap (state, ECR, OIDC deploy role) and app (VPC, RDS, Fargate, CloudFront) roots; manual OIDC deploy workflow. |

## Scheduling policy

- One synthetic clinic in `America/Chicago`, two practitioners, weekdays 09:00–17:00.
- Visit types of 30 or 60 minutes; starts on a 30-minute grid.
- At least 24 hours' notice and at most 90 days ahead (inclusive, elapsed UTC).
- Missing or ambiguous date, time, practitioner or visit type leads to a clarification;
  the backend never guesses.

## Agent loop

1. A chat request claims a short expiring lease and an increasing fence on the session,
   then releases its database transaction before calling the provider.
2. The provider, chosen by `AGENT_PROVIDER` through the registry in
   `app/agent/provider.py`, receives instructions, the selected context, three strict tool schemas
   and a strict `ReplyPlan` output schema (`store=false`, no parallel tool calls).
3. Each tool call is validated, executed and journaled with its result. After five
   calls in a turn, tool use is disabled.
4. The final `ReplyPlan` (one of `greeting`, `clarify`, `catalog`, `availability`,
   `proposal`, `confirmation_required`, `out_of_scope`) is validated and rendered from
   templates using validated tool results and fresh database reads.

Every write is fenced: a request that lost its lease cannot persist results. Context
keeps the last eight completed turns plus the current one, bounded at 24,000
characters; whole old turns are dropped, never sliced. A retried message replays its
recorded tool results instead of executing them again.

**Stale intents.** When a proposal is accepted, other unfinished turns in the session
are marked stale under the session lock. A marked turn that tries to create a proposal
gets 409 `STALE_INTENT`, so an old retry can never replace a newer choice. Turns that
predate this ordering and whose session already has proposals fail closed the same way.

## Data model

Alembic revision `0001` creates ten tables and the `btree_gist` extension. Instants are
`TIMESTAMPTZ`; sessions store only SHA-256 hashes of 256-bit random bearer tokens.

| Table | Key invariants |
| --- | --- |
| `clinics`, `practitioners`, `appointment_types`, `weekly_schedules` | Synthetic catalog; durations limited to 30/60; schedule hours checked. |
| `chat_sessions` | Token hash, fixed expiry, active turn, lease deadline, monotonic fence. |
| `chat_turns` | `UNIQUE(session_id, client_message_id)`, request fingerprint, status, stored reply. |
| `conversation_items` | Ordered JSONB items, `UNIQUE(turn_id, sequence)`, composite owner key. |
| `booking_proposals` | Immutable snapshot, TTL and status, unique source turn, one PENDING per session. |
| `appointments` | Confirmed bookings; composite FK to the exact proposal snapshot; GiST exclusion `appointments_no_overlap` on `(practitioner_id, tstzrange(starts_at, ends_at, '[)'))`. |
| `idempotency_records` | `UNIQUE(session_id, idempotency_key)`, request fingerprint, original status and body. |

## Booking and confirmation

Availability and proposals never reserve a slot. Confirmation locks the session and
proposal, checks for an existing idempotent result, revalidates policy and expiry,
inserts the appointment inside a savepoint and rechecks deadlines after any constraint
wait. An exclusion violation (SQLSTATE 23P01) rolls back the insert and records the
proposal as CONFLICTED with 409 `SLOT_TAKEN`. The appointment, the proposal status and
the idempotent result commit together. An unknown commit outcome is reported as
retryable uncertainty; retrying with the same key returns the original result.

Application services enforce business hours, grid, notice and horizon, and immutable
proposal fields. No database trigger enforces every business rule; privileged SQL is
outside the service safety boundary.

## Deployment shape

Locally, `compose.demo.yaml` runs the same images and steps as the AWS deployment;
see [testing](TESTING.md#container-stack).

| Piece | Locally | AWS sandbox (`infra/terraform/app`) |
| --- | --- | --- |
| UI | `ui` service on 8501 | One arm64 Fargate task behind an internal ALB, published only through CloudFront |
| API | `api` service, `uvicorn` on 8000 | One arm64 Fargate task, no load balancer, reachable only from the UI at `api.clinic.internal` (Cloud Map DNS) |
| Schema and catalog | One-off `migrate` service | One-off `run-task` (migrate, seed, runtime role) before each service update |
| Chat retention | `make purge-chat` | EventBridge Scheduler task running `python -m scripts.purge_chat --apply` daily |
| Database | tmpfs PostgreSQL, `DATABASE_ALLOWED_HOSTS=db` | RDS PostgreSQL 16, private subnets, `sslmode=verify-full` |

Two health endpoints: `/api/v1/health/live` never touches the database and is the
container health check; `/api/v1/health` is readiness and returns 503 when the
database is unreachable. ECS ignores a Dockerfile `HEALTHCHECK`, so the task
definitions repeat the same probes (every 30 s).

## AWS deployment

The sandbox runs in one AWS account and region (us-east-2). Every Terraform root sets
`allowed_account_ids`, so a plan or apply under any other account fails. Local runs
take credentials from the SSO profile in `AWS_PROFILE`; no provider block names a
profile, and CI uses GitHub OIDC. It is meant to be applied for a demo and destroyed
afterwards.

```text
browser --HTTPS--> CloudFront (*.cloudfront.net, HSTS) --VPC origin--> internal ALB :80
        --> UI task :8501 --> api.clinic.internal:8000 (API task) --> RDS :5432 (TLS)
```

- **Roots.** `infra/terraform/bootstrap` holds what must outlive the app: the
  versioned, TLS-only state bucket (native lock file, `use_lockfile`), the two ECR
  repositories (immutable tags, scan on push, keep 10 tagged images), the GitHub OIDC
  provider and the deploy role. `infra/terraform/app` holds everything else.
- **Network.** Tasks run in public subnets with a public IP so they can reach ECR,
  Secrets Manager and CloudWatch Logs without a NAT gateway. Security groups admit no
  inbound traffic except ALB to UI (8501) and UI to API (8000). Egress is limited to
  HTTPS for the UI, API and one-off tasks, plus PostgreSQL to the database for the API
  and one-off tasks. RDS and the internal ALB sit in private subnets with no route out
  of the VPC; RDS has no egress rules. See
  [security and privacy](docs/SECURITY_PRIVACY.md#aws-sandbox-exposure).
- **HTTPS.** CloudFront is the only public endpoint: viewer HTTP is redirected to
  HTTPS and responses carry `Strict-Transport-Security: max-age=31536000;
  includeSubDomains`. The origin is a CloudFront VPC origin pointing at an internal ALB,
  so the ALB has no public address to bypass. Caching is disabled and the AllViewer
  origin request policy forwards Host, cookies and the WebSocket upgrade, so
  Streamlit's same-origin checks see the CloudFront hostname. The ALB idle timeout is
  300 s and Streamlit pings its websocket every 30 s.
- **Database and secrets.** The master user `clinic_demo` owns the schema; its password
  is an RDS-managed secret that Terraform never sees. The runtime role `clinic_app`
  (row access only, see [database roles](docs/SECURITY_PRIVACY.md#database-roles)) gets
  a password that Terraform generates as an ephemeral value and writes to Secrets
  Manager as a write-only argument, so it is in neither state nor plan files. Task
  definitions carry password-less `DATABASE_URL`s and receive `DATABASE_PASSWORD` from
  Secrets Manager. Only the migrate task uses `clinic_demo`.
- **Task settings.** `AGENT_PROVIDER=demo`, `API_DOCS_ENABLED=false` (no Swagger, ReDoc
  or OpenAPI document), `FORWARDED_ALLOW_IPS` set to the VPC range, read-only root
  filesystems, uid 10001, logs to CloudWatch with seven-day retention. There are no task
  roles: the containers call no AWS API.
- **Deploys.** `.github/workflows/deploy.yml` (manual) builds arm64 images on a native
  runner, pushes them tagged with the commit SHA, registers new task-definition
  revisions, runs the migrate task and stops on a non-zero exit, then updates both
  services and fails if a circuit-breaker rollback left the old revision running.
  Terraform creates the first revision of each family and ignores later ones on the
  services; the purge schedule names the family without a revision, so it runs the
  latest. `terraform apply` and `destroy` are never run from CI.

### First deployment

Prerequisites: `infra/tools/install.sh` (Terraform and TFLint, SHA-256 verified),
`aws sso login --profile clinic-sandbox` and `export AWS_PROFILE=clinic-sandbox`.

1. **Bootstrap.** Its state bucket does not exist yet, so the first apply uses local
   state and then moves it into the bucket:

   ```bash
   cd infra/terraform/bootstrap
   printf 'terraform {\n  backend "local" {}\n}\n' > backend_override.tf  # gitignored
   terraform init && terraform apply
   rm backend_override.tf && terraform init -migrate-state
   rm terraform.tfstate terraform.tfstate.backup  # once the migration is confirmed
   ```

2. **GitHub environment.** In the repository settings, open Environments and create
   `aws-sandbox`. Under Deployment branches and tags choose Selected branches and add
   `main`. Under Required reviewers add yourself, leaving self-review allowed. Add the
   environment variable `AWS_DEPLOY_ROLE_ARN` with the bootstrap output
   `deploy_role_arn`. No secrets are needed: the role is assumed through OIDC, and only
   jobs in this environment can assume it.
3. **Images.** Run "Deploy to AWS sandbox" from the Actions tab on `main` and approve
   it. With no app stack yet, it only pushes the images.
4. **App.** `cd infra/terraform/app && terraform init && terraform apply -var
   image_tag=<that commit SHA>`. The services start, but the API cannot reach its
   database role until step 5.
5. **Release.** Run the deploy workflow again. It migrates, seeds, creates
   `clinic_app` and rolls both services.
6. **Check.** Open `terraform output -raw url` and run a full propose-and-confirm in
   demo mode: the page must stay connected (no "Connection error"), and
   `curl -sI http://<domain>` must answer with a redirect to HTTPS. If the websocket
   fails through the VPC origin, the fallback is an internet-facing ALB whose security
   group admits only the CloudFront origin-facing managed prefix list, with a listener
   rule that requires a secret custom header set by CloudFront. It needs no app change.

Later releases: merge to `main` and run the deploy workflow. Infrastructure changes:
`terraform apply -var image_tag=<deployed SHA>`, where the deployed SHA is the tag
printed by `aws ecs describe-task-definition --task-definition clinic-api --query
'taskDefinition.containerDefinitions[0].image'`.
To rotate the `clinic_app` password, increase `app_password_version`, apply, then run
the deploy workflow.

### Cost (us-east-2, on-demand, running all month)

| Item | USD/month |
| --- | --- |
| RDS db.t4g.micro single-AZ | 11.68 |
| RDS gp3, 20 GB | 2.30 |
| Fargate API, 0.25 vCPU / 0.5 GB arm64 | 7.21 |
| Fargate UI, 0.25 vCPU / 0.5 GB arm64 | 7.21 |
| Internal ALB, hourly plus about 0.1 LCU | 17.00 |
| Public IPv4, two task addresses | 7.30 |
| Secrets Manager, app secret plus RDS-managed secret | 0.80 |
| CloudWatch Logs, seven-day retention | ~0.50 |
| Cloud Map private DNS zone | 0.50 |
| ECR storage | ~0.30 |
| CloudFront (free tier), state bucket, scheduler, one-off tasks | ~0.10 |
| **Total** | **~55** |

That is about $0.08 an hour, so a demo applied and destroyed the same day costs well
under a dollar. Every resource carries the tag `Project=clinic-scheduling-agent`.
Budgets are managed in the AWS console, not in Terraform.

### Teardown

```bash
cd infra/terraform/app && terraform destroy -var image_tag=<deployed SHA>
```

This removes the network, database, services, load balancer, distribution, schedule,
log groups and secrets. The database keeps no final snapshot and its automated
backups are deleted; the app secret has no recovery window. Disabling the CloudFront
distribution makes the destroy take several minutes. What survives:

- the bootstrap root: state bucket (with old state versions for 90 days), OIDC
  provider, deploy role and ECR repositories with their images (cents per month);
- task-definition revisions registered by the deploy workflow (free); deregister
  them with `aws ecs deregister-task-definition` if wanted.

Removing the bootstrap root too means deleting the ECR images, removing
`prevent_destroy` from the state bucket, moving its state back to local with a
`backend_override.tf`, running `terraform destroy`, and finally deleting the remaining
object versions in the state bucket.

## Key decisions

| Decision | Rationale |
| --- | --- |
| Separate explicit confirm endpoint; no confirm tool | The model can never be the reason a booking exists. |
| Typed `ReplyPlan` plus template rendering | Visible facts come from the database, so the model cannot state a booking that did not happen. |
| PostgreSQL exclusion constraint as the overlap authority | Correct under concurrency without application locks across practitioners. |
| Durable idempotency records with original body | Lost responses are recoverable without inferring success from a timeout. |
| Stateless Responses calls with a database journal | Restarts and retries resume from recorded state; no provider-side conversation dependency. |
| REST over `httpx` instead of an SDK | Injectable transport for fully offline tests. |
| One `ResponsesProvider` protocol with a registry | `demo` and `openai` share the loop; another provider (for example Anthropic) is a new registry entry that translates its API to Responses-style items. |
| Independent graders per layer | Safe backend behaviour cannot hide a wrong model decision. |
| Migrations as a one-off task, never on container start | Concurrent tasks never race on schema changes, and a failed migration blocks the deploy instead of crash-looping the service. |
| Separate liveness and readiness | Restarts only for a dead process; database outages surface as 503 readiness, not restarts. |
| Separate schema owner and runtime database role | The long-running API holds row access only; the RDS master user, which has `rds_superuser`, is used only by the one-off migrate task. |
| Public-IP tasks instead of a NAT gateway or interface endpoints | About $22 to $51 a month cheaper; security groups admit no inbound traffic to the tasks, and egress is HTTPS only (plus PostgreSQL for the API). Interface endpoints are the upgrade path, with no app change. |
| CloudFront VPC origin to an internal ALB | HTTPS on the default certificate with no domain to buy, and no public load balancer to bypass. |
| Cloud Map DNS instead of Service Connect | No Envoy sidecar, whose recommended CPU would double each 0.25-vCPU task. |

See [API design](docs/API_DESIGN.md), [evaluation](docs/EVALUATION.md) and
[security and privacy](docs/SECURITY_PRIVACY.md).
