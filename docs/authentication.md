# Authentication Architecture

Status: proposed — no code or migrations yet. This document is the base for implementation.

Stack: FastAPI + SQLAlchemy (async) + PostgreSQL.

## 0. Context and Goals

Domain hierarchy:

```
User ──< WorkspaceMember >── Workspace ──< Calendar ──< Event
```

- A `User` can belong to many `Workspace`s (many-to-many via membership).
- A `Workspace` has many `Calendar`s.
- A `Calendar` has many `Event`s.

Auth goals:

1. Ship local email/password auth first.
2. Add OAuth providers (Google, GitHub, ...) later **without changing the core schema** — this drives the `User` / `Credential` / `UserIdentity` split below.
3. Support multi-device sessions, refresh token rotation, and full revocation (single session or all devices).
4. Be safe enough to run as a public open-source project (sane defaults, no footguns for self-hosters)i

---

## 1. Authentication Flows

### 1.1 Registration (email + password)

1. Client `POST /auth/register` with `email`, `password`, `display_name`.
2. Server validates password strength (length/entropy, not composition rules), normalizes email (lowercase, trim).
3. Server checks `users.email` uniqueness (case-insensitive).
4. Server creates:
   - `User` row, `status = unverified`.
   - `Credential` row with `password_hash` (Argon2id).
   - `EmailVerification` row with a random token (hashed at rest) and `expires_at` (~24h).
5. Server sends verification email (async job, not inline in request path).
6. Response: 201, generic message ("check your email"). Do **not** log the user in yet — no session/refresh token issued pre-verification (configurable: some products allow limited access pre-verification; default here is verify-first).

### 1.2 Email Verification

1. User clicks link `GET /auth/verify-email?token=...`.
2. Server hashes incoming token, looks up `EmailVerification` by `token_hash`, checks `expires_at` and `consumed_at IS NULL`.
3. On success: set `users.status = active`, `users.email_verified_at = now()`, mark `EmailVerification.consumed_at = now()`.
4. Token is single-use. Expired/consumed → generic error, offer "resend verification".
5. Resend endpoint is rate-limited per email/IP and invalidates prior unconsumed tokens for that user (or just lets them expire naturally — either is fine, invalidation is cleaner).

### 1.3 First Access (post-verification)

1. After verification, redirect to login (or auto-login if verification link itself is treated as an authenticated action — product decision, default: redirect to login for simplicity and auditability).
2. On first successful login, if the user has zero `WorkspaceMember` rows, the app prompts workspace creation/join. This is application-level onboarding state, not a new auth table.

### 1.4 Login

1. Client `POST /auth/login` with `email`, `password`.
2. Server loads `User` by email; if not found, run a dummy hash comparison anyway (timing-attack mitigation) and return a generic "invalid credentials".
3. Check `Credential.password_hash` with Argon2id verify.
4. Check `users.status == active` (block `unverified`/`disabled`/`deleted`).
5. Rate limit by IP and by account (see §4.6).
6. On success:
   - Create `Session` row (`user_id`, `user_agent`, `ip_address`, `created_at`, `last_seen_at`).
   - Create `RefreshToken` row bound to that `Session` (see §2.4/§4.2).
   - Issue short-lived access token (JWT) with `sid` (session id) claim.
   - Set refresh token as `httpOnly` cookie; return access token (cookie or body, see §4.3).
7. Failed attempts increment a counter (see rate limiting) but do **not** reveal whether the email exists.

### 1.5 Refresh Token

1. Client calls `POST /auth/refresh` (browser sends the httpOnly refresh cookie automatically; no body needed).
2. Server hashes the incoming raw token, looks up `RefreshToken` by `token_hash`.
3. Validate: not expired, not revoked, `used_at IS NULL`, and its `Session.revoked_at IS NULL`.
4. **Rotation**: mark current `RefreshToken.used_at = now()`, issue a brand-new `RefreshToken` row (`replaces_id` = old row's id), set new cookie.
5. **Reuse detection**: if an already-`used_at` token is presented again, treat as theft — revoke the entire `Session` (and all its refresh tokens) immediately, and optionally flag the account for review.
6. Issue a fresh short-lived access JWT.
7. Update `Session.last_seen_at`.

### 1.6 Logout (current device)

1. Client `POST /auth/logout`.
2. Server revokes the current `Session` (`revoked_at = now()`) and the associated active `RefreshToken`.
3. Clear cookies.

### 1.7 Logout of All Devices

1. Client `POST /auth/logout-all` (requires current valid session).
2. Server sets `revoked_at = now()` on **all** `Session` rows for `user_id` (or all except current, if "log out other devices" is the intended UX — expose both as distinct actions).
3. All associated `RefreshToken`s become unusable transitively (session check in §1.5 step 3 covers this — no need to touch every token row).

### 1.8 Password Recovery (forgot password)

1. Client `POST /auth/forgot-password` with `email`.
2. Server always returns 200 with a generic message regardless of whether the email exists (avoid user enumeration).
3. If the user exists: create `PasswordReset` row (hashed token, `expires_at` ~15-30 min), send email.
4. `POST /auth/reset-password` with `token`, `new_password`.
5. Server validates token (hash match, not expired, not consumed), updates `Credential.password_hash`, marks `PasswordReset.consumed_at = now()`.
6. **Revoke all existing sessions** for that user (password reset = assume compromise, force re-login everywhere).

### 1.9 Password Change (authenticated, knows current password)

1. Client `POST /auth/change-password` with `current_password`, `new_password` (requires valid access token).
2. Verify `current_password` against `Credential.password_hash`.
3. Update hash.
4. Revoke all **other** sessions (keep current session alive), or revoke all including current and force re-login — pick one and document it; default recommendation: keep current session, revoke the rest.

### 1.10 Session Revocation (user-facing device management)

1. `GET /auth/sessions` — list the user's active `Session` rows (device/user agent/IP/last_seen_at/created_at), current session flagged.
2. `DELETE /auth/sessions/{id}` — revoke one specific session (e.g., "log out that old laptop"). Must verify the session belongs to the requesting user.
3. Same mechanism backs §1.7 (revoke all = bulk version of this).

---

## 2. Entity Modeling

Separation of concerns instead of one fat `User` table — this is what lets OAuth providers get added later without touching core tables.

### `User`
Core identity. Not auth-method-specific.
- Owns profile data (email, display name, avatar, locale, timezone...).
- Owns account lifecycle state (`unverified` / `active` / `disabled` / `deleted`).
- Has **zero or one** `Credential` (users who only ever signed up via Google have none).
- Has **zero or many** `UserIdentity` (one per linked OAuth provider).

### `Credential`
The local password auth method, modeled as its own table (not columns on `User`) so:
- OAuth-only users simply don't have a row here — no nullable `password_hash` on `User` guarding half a dozen "is this a local user" checks scattered through the codebase.
- If multiple local credential *types* are ever needed (e.g. passkeys/WebAuthn as a second local factor), that's a new row shape here, not a schema migration of `User`.
- Stores: `password_hash`, `password_algorithm` (e.g., `argon2id`), `password_updated_at`.

### `UserIdentity`
One row per external OAuth identity linked to a `User`.
- `provider` (`google`, `github`, ...), `provider_user_id` (the subject/id from the provider), `user_id`.
- Optionally caches provider profile data (email at time of link, raw claims) for debugging — not authoritative.
- Unique on `(provider, provider_user_id)` — one external identity maps to exactly one `User`.
- This table is *why* adding a provider later needs zero changes to `User`/`Credential`: it's purely additive.

### `Session`
A logical login session — one per device/browser login.
- `user_id`, `user_agent`, `ip_address`, `created_at`, `last_seen_at`, `revoked_at`.
- Is the thing users see and manage in "active devices" UI.
- Is the thing that gets revoked (not individual tokens) — revoking a session invalidates every refresh token tied to it, past and future, in one check.

### `RefreshToken`
The actual rotating credential material tied to a `Session`.
- `session_id`, `token_hash` (never store the raw token), `expires_at`, `used_at` (set on rotation), `replaces_id` (self-FK, chain of rotation for audit/theft-detection), `created_at`.
- Many `RefreshToken` rows per `Session` over its lifetime (one active at a time); revoking the `Session` makes all of them dead without touching each row.

### `EmailVerification`
- `user_id`, `token_hash`, `expires_at`, `consumed_at`.
- Ephemeral, one-purpose. Old rows can be pruned by a background job.

### `PasswordReset`
- Same shape as `EmailVerification`: `user_id`, `token_hash`, `expires_at`, `consumed_at`.
- Kept as a distinct table rather than reusing `EmailVerification` — different lifetime, different security posture (reset should revoke sessions on use; verification shouldn't), and conflating them invites a future bug where one flow's token satisfies the other's endpoint.

### Domain tables (context, not detailed here)
`Workspace`, `WorkspaceMember` (join table with `role`), `Calendar`, `Event` — these exist per the product context but are out of scope for this document beyond the relationships below.

---

## 3. Relationships

```
User 1 ────── 0..1  Credential
User 1 ────── 0..N  UserIdentity
User 1 ────── 0..N  Session
User 1 ────── 0..N  EmailVerification        (historical)
User 1 ────── 0..N  PasswordReset            (historical)
Session 1 ──── 0..N RefreshToken              (rotation chain, one "active" at a time)
RefreshToken 0..1 ─ 0..1 RefreshToken         (replaces_id self-reference)
User N ──────── M  Workspace   via WorkspaceMember (role: owner/admin/member)
Workspace 1 ──── 0..N Calendar
Calendar 1 ──── 0..N Event
```

Notes:
- `Credential` and `UserIdentity` are both optional relative to `User` — a user needs **at least one** of "has a `Credential`" or "has ≥1 `UserIdentity`" (enforce in application logic, not a DB constraint — DB-level "at least one of two child tables exists" constraints are awkward in Postgres and not worth it).
- `UserIdentity` unique constraint: `(provider, provider_user_id)` — prevents the same Google account from linking to two different `User`s.
- `RefreshToken.replaces_id` forms a linked list per `Session`, letting you detect reuse of an already-rotated token (the theft-detection check in §1.5).
- Deleting a `User` should cascade to `Credential`, `UserIdentity`, `Session`, `RefreshToken`, `EmailVerification`, `PasswordReset` (all are "belongs entirely to this user" data). Cascade into `WorkspaceMember` should instead be a soft removal/ownership-transfer flow at the application level, since a workspace outliving its creator is a real scenario — don't hard-delete-cascade a `Workspace` because its owner deleted their account.

---

## 4. Security Recommendations

### 4.1 Password Hashing
- **Argon2id**, tuned to ~250-500ms server-side (e.g. via `argon2-cffi`), not bcrypt/scrypt — Argon2id is the current OWASP recommendation and resists both GPU and side-channel attacks better.
- Store `algorithm` + `hash` together so parameters can be upgraded later (rehash-on-login pattern when detecting an outdated hash).
- No password composition rules (no forced special characters); enforce a minimum length (12+) and check against a breached-password list (e.g. HaveIBeenPwned k-anonymity API) instead.
- Never log raw passwords, even at debug level.

### 4.2 Refresh Tokens
- Opaque random value (256-bit, `secrets.token_urlsafe`), **not** a JWT — refresh tokens must be revocable by DB lookup, which defeats the point of a self-contained JWT.
- Store only `token_hash` (SHA-256 is fine here — this isn't a password, it's already high-entropy random data) — a DB leak doesn't hand out usable tokens.
- Single-use, rotated on every refresh (§1.5). Reuse of a consumed token = revoke the session.
- Absolute expiry (e.g. 30-60 days) *and* consider a sliding window (refresh extends expiry) capped by an absolute maximum (e.g. 90 days) so a stolen-but-unused token doesn't live forever.

### 4.3 Access Tokens (JWT)
- Short-lived (10-15 min), stateless, used for API authorization — the whole reason to keep them short is that they can't be revoked before expiry.
- Sign with an asymmetric algorithm (EdDSA or RS256) rather than HS256 — allows other services to verify without holding the signing secret, useful once this stops being a monolith.
- Claims: `sub` (user id), `sid` (session id — lets you cross-check against `Session.revoked_at` for extra safety on sensitive endpoints), `iat`, `exp`, `jti`. Keep it minimal — no roles/permissions baked in if those can change mid-token-lifetime; look those up fresh, or accept the staleness window given the short TTL.

### 4.4 Cookies
- Refresh token: `httpOnly`, `Secure`, `SameSite=Strict` (or `Lax` if cross-site redirect flows need it), scoped `Path=/auth/refresh` to avoid sending it on every request.
- Access token: prefer cookie (`httpOnly`, `Secure`, `SameSite=Lax`, `Path=/`) over `localStorage` — avoids XSS-exfiltrated tokens; the tradeoff is needing CSRF protection (§4.7) since cookies auto-attach.
- If the API is ever consumed by third-party clients (mobile, public API), those use `Authorization: Bearer` headers instead of cookies — cookie auth is for the first-party web client only.

### 4.5 Expiration Summary

| Token | TTL |
|---|---|
| Access (JWT) | 10-15 min |
| Refresh | 30-60 days sliding, 90 days absolute cap |
| Email verification | 24h |
| Password reset | 15-30 min |

### 4.6 Rate Limiting
- Login: per-IP and per-account (e.g. 5 attempts/min, exponential backoff, temporary lockout after N failures — lockout duration, not permanent, to avoid a DoS-via-lockout griefing vector).
- Password reset request / email verification resend: throttle per email and per IP (prevents email-bombing).
- Refresh endpoint: loose per-session rate limit, mainly to catch automated abuse rather than legitimate use.

### 4.7 CSRF
- Only relevant because of cookie-based auth (§4.4).
- Primary defense: `SameSite=Lax`/`Strict` cookies already block most cross-site request forgery.
- Belt-and-suspenders: require a custom header (e.g. `X-Requested-With`) on state-changing requests — simple `<form>`-based CSRF can't set custom headers, so this alone blocks the classic attack even if `SameSite` is somehow bypassed.
- If cross-origin cookie use is ever needed (`SameSite=None`), add a double-submit CSRF token.

### 4.8 Misc
- Revoke all sessions on password change/reset (§1.8/1.9).
- Generic error messages for login/forgot-password to avoid account enumeration.
- Structured audit logging of auth events (login, logout, password change, failed attempts) — not modeled as a table in §2 since it's operational/observability data, not auth state; a separate `AuditLog` can be added later without touching this schema.

---

## 5. Naming Conventions

- **Tables**: `snake_case`, plural — `users`, `credentials`, `user_identities`, `sessions`, `refresh_tokens`, `email_verifications`, `password_resets`, `workspaces`, `workspace_members`, `calendars`, `events`.
- **Columns**: `snake_case` — `password_hash`, `provider_user_id`, `expires_at`.
- **Primary keys**: `id`, type `UUID`. Prefer **UUIDv7** (time-ordered) over UUIDv4 — keeps B-tree index locality sane at scale, unlike random v4 UUIDs, while still being non-guessable/non-sequential-int.
- **Foreign keys**: `<singular_referenced_table>_id` — `user_id`, `session_id`, `workspace_id`.
- **Timestamps**: always `timestamptz`, always UTC. Standard pair `created_at` / `updated_at` on every table. Lifecycle-specific columns named for what they mean, not generically: `expires_at`, `consumed_at`, `used_at`, `revoked_at`, `email_verified_at`, `last_seen_at` — more informative than a bare `status` flag and each is independently queryable/indexable.
- **Booleans**: prefix `is_`/`has_` — `is_active`. Prefer an explicit status enum (`status: unverified|active|disabled|deleted` on `users`) over a pile of booleans once there are more than two states.
- **Soft delete**: **not** for the auth tables in §2 — `Session`/`RefreshToken`/`EmailVerification`/`PasswordReset` already have precise lifecycle timestamps (`revoked_at`, `consumed_at`, `expires_at`); bolting a generic `deleted_at` on top adds a second, redundant "is this row alive" axis. `User` itself: use the `status` enum (`deleted` as a status, not a hard delete) so audit/foreign-key history stays intact. Domain entities (`Workspace`, `Calendar`, `Event`) are a separate call — soft delete (`deleted_at`) is reasonable there since "recover an accidentally deleted calendar" is a real product feature; not covered further in this document.
- **Enums**: represent as Postgres `TEXT` + `CHECK` constraint (or native `ENUM` type if the team prefers — `CHECK` is easier to alter later without a type migration) rather than raw integers, for readability in raw SQL/psql during incident response.

---

## 6. Open Decisions (flag for review before implementation)

1. Access token delivery: cookie vs. `Authorization` header for the first-party web client (this doc recommends cookie).
2. Whether login is allowed at all pre-email-verification (this doc recommends: no).
3. Password change: revoke current session too, or keep it alive (this doc recommends: keep current alive, revoke others).
4. Native Postgres `ENUM` vs `TEXT + CHECK` for status/provider/role columns.
