# RFC: Mail Module — Ember as a Workspace Platform

Status: proposed — research and architecture only. No code or migrations yet.
This document follows the precedent set by `docs/authentication.md`: design
first, implement against the document.

Stack today: FastAPI + SQLAlchemy (async) + PostgreSQL (`core/`), Next.js
standalone + shadcn (`web/`), Alembic migrations applied on API container
start, deployed via docker-compose on Coolify with an **external** Postgres.

---

## 0. What the codebase looks like right now

Every recommendation below is grounded in the current repository, so first a
factual inventory.

### 0.1 Architecture

```
core/ember/
├── config.py          # venvalid-validated env (DATABASE_URL, JWT, TTLs…)
├── db.py              # async engine, get_db(), naming conventions
├── dependencies.py    # get_current_user (JWT + session revocation check)
├── jwt.py             # HS256 access tokens with sid claim
├── security.py        # Argon2id passwords, SHA-256 token hashing at rest
├── models/            # one file per entity, flat
├── schemas/           # Pydantic request/response, validation lives here
├── services/          # domain logic, raises domain errors, owns flush()
└── routers/           # thin HTTP layer, maps domain errors → status codes
```

Patterns that the Mail module must respect because they are load-bearing:

- **Layered, not modular.** There is no package-per-domain; domains are split
  across `models/`, `schemas/`, `services/`, `routers/`. Feature = one file in
  each layer + a migration + two test files (`test_X_api.py`,
  `test_X_service.py`) against a real Postgres.
- **Workspace is the tenancy boundary.**
  `User ──< WorkspaceMember >── Workspace ──< Calendar ──< Event`. Roles are
  `owner | member` only. Membership checks live in
  `services/workspaces.assert_workspace_member`.
- **404, never 403.** A non-member cannot even confirm a resource id exists
  (`routers/workspaces.py`, `routers/events.py`).
- **Secrets are hashed at rest.** Refresh tokens, invite codes — raw value
  returned exactly once, SHA-256 stored. Signup is invite-gated and invites
  are claimed atomically (UPDATE … WHERE used_at IS NULL).
- **No background jobs.** Everything is request/response. The auth design doc
  already anticipates async jobs ("send verification email (async job)") that
  were never built — **Ember currently sends no email at all**; invites are
  copy-paste links precisely because there is no mail infrastructure.
- **Config is env-only** (venvalid), secrets never in files; deploy is
  docker-compose (api + web) against an external database, migrations run at
  api start (`alembic upgrade head && uvicorn …`).

### 0.2 What is missing that Mail will force us to build

1. A background job runner (sync, retries, indexing cannot be request/response).
2. Reversible secret storage (mail server credentials cannot be one-way hashes).
3. A module boundary convention — the flat layout works at 6 entities; a
   workspace platform (Mail, later Drive/Notes/Chat) needs bounded contexts.

---

## 1. High-level vision

Ember's README already frames it as more than a calendar: *"Private,
self-hosted alternative"*. The natural evolution is **Ember as a self-hosted
workspace**: one identity, one tenancy model (Workspace), N modules. Calendar
is module #1; Mail is module #2 and the template for every module after it.

How Mail relates to the existing domains:

| Existing concept | Relationship to Mail |
|---|---|
| **User** | Owns personal mail accounts; is the actor for send/read/delete. |
| **Workspace** | Tenancy boundary. Mail accounts, shared mailboxes, and mail domains hang off a workspace exactly like calendars do. |
| **WorkspaceMember / roles** | Gate who can see a shared mailbox, who can administer the workspace's mail domain. |
| **Authentication** | Same JWT + session model; mail endpoints use `get_current_user` unchanged. Ember remains the single identity source — the mail server must not become a second user database. |
| **Calendar / Event** | Deep integration target: inbound ICS invitations become Events; `EventAttendee` (already email-only by design) becomes the bridge for outbound invitations. |
| **Invites** | Today invites are copy-paste links because Ember cannot send email. Mail infrastructure finally lets signup/verification/invite emails exist (the flows §1.1–1.2 of `docs/authentication.md` deferred). |

Non-goals: Ember does not aim to be a mail *server* product (Mailcow already
exists). It aims to be a mail *client + collaboration layer* over
infrastructure it orchestrates.

---

## 2. Proposed architecture: which shape should Mail take?

Four candidate shapes, evaluated against the actual deploy target (a single
Coolify box, one compose file, an external Postgres, one maintainer):

### Option A — pure internal module (Ember implements SMTP/IMAP itself)
Rejected. See §3; this is years of protocol and deliverability work that has
nothing to do with Ember's value.

### Option B — external microservice (separate "ember-mail" API service)
Rejected for now. A second FastAPI service means duplicated auth, duplicated
deploy, network contracts, and versioning — costs that pay off with multiple
teams. Ember has one codebase, one test suite, one deploy unit. The
authentication doc's philosophy ("sane defaults, no footguns for
self-hosters") argues against gratuitous distribution.

### Option C — wrapper around a full groupware suite (Mailcow / iRedMail)
Rejected. These bundle their own UIs, user databases, and admin panels —
Ember would be skinning someone else's product and fighting its identity
model. They are also heavy (Mailcow ≈ a dozen containers), hostile to the
"one compose file on Coolify" story.

### Option D — **internal Ember module + dedicated mail server container** ✅
Mail is a first-class module *inside* the existing FastAPI app (same auth,
same DB, same test suite, same deploy), and all wire-protocol work (SMTP,
IMAP/JMAP, DKIM, queues, spam) is delegated to a purpose-built mail server
running as one more compose service. Ember talks to it over **JMAP** and its
management API. This is exactly the relationship Ember already has with
PostgreSQL: essential infrastructure, someone else's codebase.

**Recommended mail server: [Stalwart](https://stalw.art).** Reasons, compared
against the alternatives researched:

| Server | Shape | Fit for Ember |
|---|---|---|
| **Stalwart** | Single Rust binary; SMTP+IMAP+**JMAP** in one; HTTP management API; built-in DKIM signing, spam filtering, full-text search; can use Postgres as its backing store | **Best fit.** One extra container, JMAP-native (JSON over HTTP — no IMAP parsing in Python), programmatic account provisioning, OIDC-capable for future SSO with Ember. |
| Mailcow | ~12 containers (Postfix, Dovecot, Rspamd, SOGo, MySQL, Redis…) | Too heavy; brings its own UI/user DB. |
| Docker Mailserver | Single container, Postfix+Dovecot, config-file driven | Lean, but IMAP-only (no JMAP) and account management via files/scripts — awkward to orchestrate from an API. Viable fallback. |
| Mail-in-a-Box | Owns the whole machine (DNS, TLS, everything) | Incompatible with Coolify co-tenancy. |
| iRedMail | Installer that owns the host, web admin panel | Same problem; not container-first. |

Trade-off accepted: Stalwart is younger than Postfix/Dovecot. Mitigation: all
Ember⇄mail-server communication goes through one adapter interface
(`MailServerClient`) so the backend is swappable; JMAP is an open standard
(RFC 8620/8621), not a Stalwart API.

### Module layout: introduce the bounded-context convention

Mail should **not** add 8 more files to each flat layer. Proposed structure —
the template for every future module:

```
core/ember/
├── mail/
│   ├── models.py        # or models/ if it outgrows one file
│   ├── schemas.py
│   ├── services/
│   │   ├── accounts.py
│   │   ├── messages.py
│   │   └── sync.py
│   ├── router.py        # APIRouter(prefix="/api/mail")
│   ├── client.py        # MailServerClient (JMAP + management API adapter)
│   └── jobs.py          # background tasks
├── models/ …            # existing domains stay flat; migrate opportunistically
```

Existing code is not reshuffled now (churn without user value); the shared
kernel (`db.py`, `config.py`, `dependencies.py`, `security.py`,
`services/workspaces.assert_workspace_member`) is what modules import.

---

## 3. Why not implement SMTP ourselves?

Because "sending email" is a distributed-systems and *reputation* problem
wearing a protocol costume:

- **SMTP** itself is the easy 10%: greeting, EHLO, pipelining, STARTTLS,
  8BITMIME/SMTPUTF8, and then the hard 90% — **queues and retries** with
  exponential backoff over days, bounce classification (4xx vs 5xx), DSN
  generation, connection caching per destination MX, per-domain throttling so
  Gmail doesn't tempfail you.
- **IMAP** is a 30-year accretion of state: folder subscriptions, UIDVALIDITY,
  CONDSTORE/QRESYNC, IDLE, flags sync, partial fetches. Implementing a correct
  IMAP *client* in Python is months; a server is worse. **JMAP** (RFC
  8620/8621) exists precisely because of this pain — JSON, HTTP, batched,
  push-capable — but only modern servers (Stalwart, Cyrus) speak it.
- **Authentication stack for deliverability**: **SPF** (DNS TXT authorizing
  sending IPs), **DKIM** (per-domain key pairs, canonicalization, signing every
  outbound message, key rotation), **DMARC** (policy + aggregate report
  processing), plus **MX/PTR/rDNS** correctness and **MTA-STS/TLS-RPT** if done
  properly. Any mistake ⇒ silent spam-foldering.
- **TLS**: certificate lifecycle for SMTP (implicit 465 + STARTTLS 587/25),
  cipher policy, DANE if ambitious.
- **Spam, both directions**: inbound filtering (Rspamd-class: bayes, DNSBL,
  greylisting, rate limits) and outbound abuse prevention so one compromised
  account doesn't torch the server's reputation.
- **IP reputation** is the killer: it is not code at all. Fresh IPs are
  presumed guilty; warm-up takes weeks of gradually increasing volume;
  self-hosters on residential/cloud IPs often *cannot* get port 25 opened.
  This must be an operational concern with documented escape hatches (smart
  host / relay through the provider), not something Ember's Python code can
  solve.

Every hour spent reimplementing this is an hour not spent on what Ember is
actually for. Stalwart ships all of the above (queues, retries, DKIM signing,
spam filter, IMAP+JMAP, ACME TLS) in one audited binary. **Ember's job is
orchestration and UX, not MTA engineering.**

---

## 4. Recommended architecture

```
                    Browser
                       │  (same-origin /api/* — unchanged)
                ┌──────▼──────┐
                │  web (Next) │  /mail UI, three-pane inbox
                └──────┬──────┘
                       │ proxy (next.config.ts rewrite, unchanged)
                ┌──────▼──────────────────────────────┐
                │  api (FastAPI)                      │
                │  ├─ existing routers (auth, events…)│
                │  ├─ ember/mail/router.py            │
                │  ├─ ember/mail/services/*           │
                │  └─ ember/mail/client.py ───────────┼───┐
                └──────┬──────────────────────────────┘   │ JMAP (RFC 8620/8621)
                       │                                  │ + management HTTP API
                ┌──────▼──────┐        ┌──────────────────▼─┐
                │  worker     │        │  stalwart (mail)   │
                │  (jobs: sync│◄──────►│  SMTP 25/465/587   │
                │  send,index)│  JMAP  │  IMAP 993 (interop)│
                └──────┬──────┘        │  JMAP/HTTP 8080    │
                       │               │  DKIM, queues, spam│
                ┌──────▼──────┐        └──────────┬─────────┘
                │  PostgreSQL │◄──────────────────┘
                │  (external) │   Stalwart can persist to Postgres too
                └─────────────┘   (separate database/schema, same server)
```

Communication contracts:

1. **Provisioning** (api → Stalwart management API): create/disable mail
   accounts, set quotas, manage domains and DKIM keys when a workspace enables
   mail. Wrapped entirely inside `MailServerClient`.
2. **Reading/sync** (worker ⇄ Stalwart JMAP): `Email/query`,
   `Email/changes`, `Mailbox/get`, blob download. Incremental sync driven by
   JMAP state strings; push via EventSource where available, polling fallback.
3. **Sending** (api → worker → Stalwart JMAP `EmailSubmission/set`):
   submission is a job, never inline in the request — the HTTP request returns
   as soon as the outbox row is durably queued.
4. **Inbound notification** (Stalwart webhook → api): new-message events flip
   a sync job; absence of webhooks degrades gracefully to short polling.

DNS (MX, SPF, DKIM TXT, DMARC) stays an **operator runbook** (documented in
`docs/`, surfaced as a checklist in the UI with live verification), because no
container can set someone's DNS.

---

## 5. Domain model (Ember-side entities, not implemented yet)

Source-of-truth split is the key design decision: **the mail server owns raw
messages (RFC 5322 bytes, blobs); Ember's Postgres owns metadata, workspace
mapping, and collaboration state.** Ember rows always carry the JMAP ids
needed to fetch the authoritative object.

| Entity | Responsibility |
|---|---|
| **MailDomain** | A sending/receiving domain owned by a workspace (`ember.example.com`). Tracks DNS verification state (MX/SPF/DKIM/DMARC checks), DKIM selector. FK → Workspace. |
| **MailAccount** | An address on a domain (`felipe@…`). Personal (FK → User) or shared (FK → Workspace, no user). Holds Stalwart account id + encrypted credential reference, quota, signature. The analogue of `Calendar` in the tenancy tree. |
| **Mailbox** | A folder within an account (Inbox, Sent, Drafts, Archive, custom). Mirrors JMAP Mailbox objects (`jmap_id`, role, parent, counts). Synced, not user-created-only. |
| **Thread** | Conversation grouping (JMAP Thread id). Denormalizes subject, participants, last activity, unread count for list rendering without N queries. |
| **Message** | Metadata row: JMAP Email id, thread FK, mailbox FKs, from/to/cc (JSONB), subject, preview snippet, sent/received timestamps, flags (seen/answered/flagged), `has_attachments`, size. **Not** the body. |
| **MessageBody** | Optional cached body (sanitized HTML + plaintext) with fetch timestamp — a cache with eviction policy, never the source of truth. |
| **Attachment** | Metadata: filename, MIME type, size, JMAP blob id. Bytes stay in Stalwart blob storage; Ember streams them through on demand. |
| **Label** | Workspace- or account-scoped tags, colored like `Calendar.color`. M:N to Message. Maps to JMAP keywords where possible so IMAP clients see them too. |
| **Contact** | Auto-harvested from correspondence + manual entries. Feeds compose autocomplete **and** `EventAttendee` autocomplete — first shared asset between modules. |
| **MailboxGrant** | Delegated access: (mail_account, user, permission ∈ read/send/manage). Powers shared inboxes and "send on behalf of". |
| **OutboxEntry** | Durable send queue on Ember's side: draft snapshot, submission state (queued → submitting → sent/failed), retry count, error. Lets the UI show "sending…" truthfully and enables undo-send (delayed submission). |

Deliberately absent: a `MailUser`. Users are Ember users; Stalwart accounts
are provisioned artifacts owned by `MailAccount`, invisible as identities.

---

## 6. Permissions

Reuse the existing model, extend minimally:

- **Personal mailbox**: `MailAccount.user_id = X` → only user X (and nobody
  else, not even the workspace owner) can read/send. Workspace owner can
  *administer* (disable, delete, re-assign address) but not read — the same
  separation Google Workspace admins have.
- **Shared/company mailbox** (`support@…`): `MailAccount.user_id IS NULL`,
  access via `MailboxGrant` rows. Any workspace member with a `read` grant
  sees it in their sidebar; `send` grant allows replying as the mailbox;
  `manage` allows granting others.
- **Workspace admin concerns** (domains, DKIM, creating accounts): gate on
  `WorkspaceRole.OWNER` today. The `owner|member` enum is already
  string-typed (`native_enum=False`), so adding `ADMIN` later is a data
  migration, not a schema fight.
- **Enforcement pattern**: identical to calendars — resolve
  MailAccount → workspace, `assert_workspace_member`, then check
  ownership/grant; return **404** (not 403) on any failure, per the invariant
  in `routers/workspaces.py`.
- **Delegated access** ("assistant reads my inbox") is just a `MailboxGrant`
  on a personal account, created by its owner — same mechanism as shared
  mailboxes, no special case.

---

## 7. Storage

| Data | Where | Why |
|---|---|---|
| Raw RFC 5322 messages, blobs | **Stalwart** (its Postgres schema or filesystem) | It's the IMAP/JMAP source of truth; duplicating it doubles storage and creates divergence bugs. |
| Message/Thread/Mailbox metadata | **Ember Postgres** | List views, unread counts, labels, workspace mapping, cross-module queries — cannot round-trip to JMAP per page load. |
| Sanitized bodies | **Ember Postgres, as cache** (`MessageBody`) | Fetched on first open, kept for recent/starred messages, evicted by age+size budget. Cheap re-fetch by blob id. |
| Attachments | **Stalwart blobs**, streamed through Ember | Ember adds authz on the stream; no second copy. |
| Search index | See §8 | |

Rejected extremes:

- **Full-copy in Ember** (store every message body + attachment): storage
  doubles, backup doubles, sanitization bugs become data corruption, and
  Stalwart's own FTS/IMAP access is wasted. Only justified if we ever allow
  *external* IMAP accounts (fetching Gmail into Ember) — revisit then.
- **Metadata-only, no cache**: every message open = JMAP round trip + HTML
  sanitization; sluggish UI, hammers the mail server.

Operational notes: Ember's DB backup and Stalwart's storage backup must be
documented as a **pair** (restore skew = metadata pointing at missing blobs;
mitigated by treating Ember rows as re-syncable from Stalwart — the sync job
doubles as repair). Quotas enforced in Stalwart per account, surfaced in
Ember's UI.

---

## 8. Search

Three tiers, adopt in order:

1. **Phase 1 — delegate to JMAP `Email/query`.** Stalwart has built-in
   full-text search; Ember forwards the query and hydrates results from local
   metadata. Zero new infrastructure, good enough for launch.
2. **Phase 2 — Postgres FTS on Ember metadata** (`tsvector` over subject,
   participants, snippet, label names; GIN index). Powers *fast* typeahead,
   filters (`from:`, `label:`, `has:attachment` map to indexed columns), and —
   the real prize — **cross-module workspace search** ("show everything about
   'contract renewal'" across Mail + Calendar). Postgres FTS is already in the
   stack; no Elastic to babysit — aligned with the self-hoster ethos.
3. **Tier 3 — external engine (Meilisearch/Typesense)** only if measured
   relevance/scale pain demands it. Not planned; noted as the escape hatch.

Body-content search stays delegated to Stalwart (it has the bodies); Ember FTS
covers metadata. Combined UX: metadata hits instantly, "search full text"
expands via JMAP.

---

## 9. Background processing

Mail is what finally forces a job runner into Ember. Recommendation:
**Procrastinate** — a Postgres-based async task queue (LISTEN/NOTIFY, no
Redis/broker). Rationale: the deploy story stays "app + mail server +
external Postgres"; jobs are transactional with domain writes (enqueue in the
same transaction that creates the `OutboxEntry` — no lost sends); it's
async-native like the rest of `core`. A `worker` service in compose runs the
same image with a different command.

Jobs:

| Job | Trigger | Notes |
|---|---|---|
| `send_message` | OutboxEntry created | JMAP `EmailSubmission/set`; retries with backoff; terminal failure marks entry failed + notifies UI. Undo-send = scheduled with delay. |
| `sync_account_incremental` | Stalwart webhook, or schedule (30–60s) | JMAP `*/changes` from last state string; upserts Message/Thread/Mailbox rows. Idempotent. |
| `sync_account_initial` | MailAccount created | Paged backfill, newest-first so Inbox is usable immediately. |
| `fetch_body` | first message open (inline fast-path w/ job fallback) | Sanitize HTML, cache into MessageBody. |
| `process_attachments` | message with attachments synced | Metadata extraction; later: thumbnails, ICS detection (§calendar integration). |
| `reindex_search` | message upsert (Phase 2 FTS) | Maintain tsvector columns. |
| `evict_body_cache` | cron | Enforce cache budget. |
| `verify_dns` | domain setup + daily cron | Check MX/SPF/DKIM/DMARC records, update MailDomain status, surface in UI checklist. |
| `harvest_contacts` | message synced | Upsert Contact rows. |

Immediate side benefit: the deferred auth flows (verification email, password
reset, invite delivery — `docs/authentication.md` §1.1–1.2, §1.8) become
trivial `send_message` calls on a system account.

---

## 10. API design

Same conventions as today: Bearer JWT via `get_current_user`, workspace
scoping in the path where tenancy applies, service layer raises domain errors,
router maps to status codes, 404-not-403, Pydantic schemas with validators.

```
# Domains & accounts (admin)
POST   /api/workspaces/{workspace_id}/mail/domains          # add domain, returns DNS checklist
GET    /api/workspaces/{workspace_id}/mail/domains
POST   /api/workspaces/{workspace_id}/mail/accounts          # provision address (personal or shared)
GET    /api/workspaces/{workspace_id}/mail/accounts          # accounts current user can see
POST   /api/mail/accounts/{account_id}/grants                # delegate / share
DELETE /api/mail/accounts/{account_id}/grants/{grant_id}

# Mailboxes & messages (client surface)
GET    /api/mail/accounts/{account_id}/mailboxes
GET    /api/mail/mailboxes/{mailbox_id}/threads?cursor=…     # paginated thread list
GET    /api/mail/threads/{thread_id}                         # thread with messages (bodies lazy)
GET    /api/mail/messages/{message_id}/body
GET    /api/mail/messages/{message_id}/attachments/{id}      # authz'd stream from blob
PATCH  /api/mail/messages/{message_id}                       # flags: read/star; move; labels
DELETE /api/mail/messages/{message_id}                       # → Trash (soft), purge via mailbox role

# Compose
POST   /api/mail/accounts/{account_id}/drafts
PATCH  /api/mail/drafts/{draft_id}
POST   /api/mail/drafts/{draft_id}/send                      # creates OutboxEntry, 202 Accepted
POST   /api/mail/outbox/{entry_id}/cancel                    # undo-send window
GET    /api/mail/outbox                                      # pending/failed sends

# Search & labels & contacts
GET    /api/mail/search?q=…&account_id=…                     # metadata-first, JMAP expand
POST   /api/mail/labels        GET /api/mail/labels
GET    /api/mail/contacts?q=…                                # shared with EventAttendee autocomplete
```

`POST …/send` returning **202 + OutboxEntry** (instead of blocking on SMTP) is
the one deliberate departure from the current all-synchronous style — sending
mail is not a request/response operation and the API should not pretend it is.

---

## 11. Frontend considerations

Reuse the workspace shell wholesale — Mail is a sibling of the calendar view,
not a separate app:

- **Navigation**: the existing sidebar gains a module switcher (Calendar /
  Mail). Route: `/workspace/{workspaceId}/mail`. Same fixed dark theme
  (`#121212`, `#21103b` accent), same shadcn primitives.
- **Layout**: three-pane — mailbox/label list (reusing sidebar section
  patterns from `sidebar.tsx`), thread list with unread emphasis + snippet,
  thread view. Panes collapse like the current sidebar for smaller screens.
- **Compose**: modal following `event-dialog.tsx` conventions (frosted
  backdrop, chip inputs — the guest-email chips are literally reusable for
  To/Cc/Bcc), plus minimize-to-corner for long drafts. Autosave to the drafts
  endpoint.
- **Thread view**: collapsed quoted history, sanitized HTML in a sandboxed
  iframe, remote images blocked by default (privacy default befitting
  self-hosted), attachment cards with download/preview.
- **Labels**: colored dots + checkbox visibility, identical interaction
  grammar to "My calendars" in the current sidebar.
- **Search**: header omnibox with `from:` `label:` `has:` token affordances.
- **Send state**: outbox indicator with undo-send countdown, mirroring the
  optimistic-then-refetch pattern `workspace-view.tsx` already uses.
- **Calendar bridge UI**: an inbound ICS renders as an invitation card
  (Accept/Decline → creates/updates the Event and RSVPs by mail); "email
  guests" on an Event opens compose pre-filled from `EventAttendee`.

---

## 12. Roadmap

Each phase = migration(s) + service + router + API/service tests + UI,
matching the repo's existing per-feature commit discipline.

- **Phase 0 — foundations** (no user-visible mail):
  Procrastinate worker service; `MailServerClient` adapter + Stalwart in
  compose (behind an `ENVIRONMENT`-style feature flag); encrypted-secret
  helper in `security.py` (Fernet w/ env master key) for server credentials.
  Exit criterion: system emails work — invite links (`invite-members.tsx`) can
  be *sent*, auth verification flows unblock.
- **Phase 1 — accounts & reading**: MailDomain (DNS checklist + `verify_dns`),
  MailAccount provisioning, initial + incremental sync, mailbox/thread/message
  read API, three-pane UI, flags (read/star). Personal accounts only.
- **Phase 2 — sending**: OutboxEntry, `send_message` job, compose modal,
  reply/reply-all/forward, undo-send.
- **Phase 3 — drafts**: server-side drafts, autosave, resume-editing.
- **Phase 4 — attachments**: upload to blob on compose, authz'd streaming
  download, attachment cards; ICS detection groundwork.
- **Phase 5 — search & labels**: JMAP-delegated search, then Postgres FTS
  metadata tier; label CRUD + filters.
- **Phase 6 — shared mailboxes & delegation**: MailboxGrant, shared inbox UX,
  send-as, owner-role admin screens.
- **Phase 7 — calendar integration**: inbound ICS → invitation card → Event;
  outbound event invitations via mail; unified contact autocomplete; the
  point where Ember stops being two modules and starts being a workspace.

Phases 1–2 are the minimum lovable product; everything after ships
independently.

---

## 13. Risks

| Risk | Assessment & mitigation |
|---|---|
| **Deliverability / IP reputation** | The #1 practical risk and it is *operational*, not code. Self-hosters on cloud IPs may find port 25 blocked outright. Mitigate: first-class **smart-host/relay mode** (route outbound through the user's provider or a relay service) as a supported configuration, DNS checklist UI, honest docs. Never promise inbox placement. |
| **Sync correctness** | Two databases (Stalwart, Ember) describing the same messages. Mitigate: one-directional authority (server → Ember), idempotent upserts keyed on JMAP ids + state strings, and a `resync` repair job; Ember metadata is *rebuildable by design*. |
| **Storage growth** | Mail dwarfs calendar data; attachments dominate. Mitigate: quotas per account (enforced in Stalwart), body-cache eviction, storage dashboards for the operator. |
| **Backups** | Ember DB and Stalwart store must be restored as a pair. Mitigate: document the pairing; rely on rebuildability of Ember-side metadata to tolerate skew. |
| **Security surface** | HTML email = XSS delivery vehicle; attachments = malware. Mitigate: strict server-side sanitization + sandboxed iframe + CSP, remote images off by default, no inline JS ever; mail-server credentials encrypted (never plaintext, never logged), reusing the "hashed/encrypted at rest, raw shown once" discipline. |
| **Spam (inbound & outbound)** | Delegated to Stalwart's filter; Ember surfaces spam folder + train-as-spam. Outbound rate limits per account so one compromised password doesn't burn the domain. |
| **Job runner is new infrastructure** | First async component; failure modes (stuck queue, poisoned job) are new to the codebase. Mitigate: Postgres-native queue keeps it inspectable with SQL; dead-letter states surfaced in an ops endpoint; worker is stateless and restartable. |
| **Coupling to Stalwart** | Younger project than Postfix. Mitigate: `MailServerClient` adapter + JMAP-standard protocol keeps a Docker-Mailserver(-style) fallback plausible; no Stalwart-proprietary concepts leak into domain models. |
| **Scope creep** | Mail clients are bottomless (snooze, rules, PGP, mobile push…). Mitigate: the roadmap above is the contract; anything not listed is a new RFC. |
| **Single-node scalability** | Sync jobs + FTS on one box have limits. Acceptable: Ember targets self-hosted workspaces (tens of users), not SaaS scale; the worker split already gives the first horizontal seam if needed. |

---

## Appendix: decision summary

1. **Mail = internal module** in `core/ember/mail/` (bounded-context package —
   the template for future modules), not a microservice.
2. **Stalwart** as the mail server container; Ember speaks **JMAP** + its
   management API through a swappable `MailServerClient` adapter. Ember never
   implements SMTP/IMAP.
3. **Metadata in Ember Postgres, messages in the mail server**; bodies cached,
   attachments streamed, Ember rows rebuildable.
4. **Procrastinate (Postgres-native) worker** as Ember's first background-job
   infrastructure; sending is always async (202 + outbox).
5. **Permissions reuse the workspace model** (owner-gated admin, grants for
   shared/delegated mailboxes, 404-not-403 everywhere).
6. **Search**: JMAP-delegated first, Postgres FTS second, external engines
   only under proven need.
7. **Deliverability treated as an operational product feature** (DNS
   checklist, relay mode, honest docs), not an afterthought.
