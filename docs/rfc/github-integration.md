# RFC: GitHub Integration — Issues Inside Ember

Status: implemented. This document follows the precedent set by
`docs/authentication.md` and `docs/rfc/mail-module.md`: the design is written
down so the code can be read against an intent rather than reverse-engineered.

---

## 1. The problem

Ember has a Boards feature (`web/app/workspace/[workspaceId]/boards/`) where
tasks live as `Entity` rows projected onto `Board` / `BoardColumn` /
`BoardCard`. But real engineering work lives in GitHub issues, spread across
personal repositories and organization repositories. Knowing what is assigned,
what is open, and filing something new all mean leaving Ember.

The goal is narrow and deliberately so:

1. see issues from selected repositories, with assignees, labels, and status;
2. create new issues in a chosen repository.

**Non-goals**, each a real decision rather than an omission:

| Not doing | Why |
|---|---|
| Bidirectional sync | Ember would become a second source of truth for issue state, and every conflict would need a resolution policy nobody asked for. |
| Webhooks | They require a publicly reachable URL and a secret per repository. Polling with a short cache is enough for a board a human looks at. |
| A local mirror table | A mirror is a sync problem wearing a database schema. Live reads are simpler and cannot go stale. |
| GitHub Projects v2 | GraphQL-only, and its custom fields do not map onto anything Ember has. Repositories are where issues actually live. |
| Pull requests | They come back from the issues endpoint, and are filtered out (§5). A PR is not a task. |
| GitHub as a login method | This is an *integration* credential, not an identity. See §7. |

---

## 2. Why an OAuth App

Three options, one chosen.

**OAuth App (chosen).** One "Connect GitHub" step. The token acts as the user,
so it reaches exactly the repositories they can already reach — personal and
organization alike — with no per-organization setup. For a self-hosted tool
where the operator and the user are usually the same person, this is the right
amount of ceremony.

**GitHub App (rejected).** Better isolation and fine-grained permissions, but it
needs a private key, an app JWT, an installation flow per organization, and
installation-token refresh. That is a large amount of machinery for a feature
whose whole job is to list issues.

**Personal Access Token (rejected).** No handshake to build, but it puts a
long-lived, broadly-scoped credential in a text field, asks every user to mint
and rotate it by hand, and gives Ember no way to tell a revoked token from a
typo.

Scopes requested: `repo read:org`. `repo` because GitHub has no issues-only
scope for OAuth Apps — this is the integration's main privacy cost and is worth
stating plainly. `read:org` so organization repositories appear in the picker.

---

## 3. Two scopes, on purpose

- **The connection is per user.** `github_connections.user_id` is unique. The
  grant belongs to the person who approved it, and every call runs as them.
- **Tracked repositories are per workspace.** `github_tracked_repos` is keyed by
  `(workspace_id, repo_id)`, so which repositories a board shows is shared team
  configuration rather than a private list each member rebuilds.

The tracked table is also **the allowlist**. Every read and every issue creation
resolves a numeric `repo_id` through it; no endpoint accepts a caller-supplied
`owner/name`. Without that, any workspace member could aim another member's
token at an arbitrary repository.

`repo_id` is GitHub's numeric id rather than the name, because it survives
renames and transfers. `full_name` is stored alongside it purely for display.

---

## 4. Credentials at rest

`ember/security.py` hashes — correct for passwords, refresh tokens, and invite
codes, none of which Ember ever needs to read back. An OAuth access token is the
opposite: it must be replayed to GitHub on every call.

So `ember/crypto.py` adds the one reversible primitive in the codebase: Fernet
(AES-128-CBC + HMAC-SHA256, authenticated) keyed by
`GITHUB_TOKEN_ENCRYPTION_KEY`. Both the access token and the refresh token are
stored as ciphertext.

`github_configured()` requires the client id, the client secret, **and** the
encryption key. A half-configured integration reads as *disabled* rather than
falling back to storing a credential in plaintext.

There is no key rotation story. Rotating the key invalidates every stored token
and affected users reconnect — acceptable for a self-hosted deployment, and
better than pretending re-encryption is handled.

---

## 5. The client seam

`ember/github/` mirrors `ember/mail/`:

- `client.py` — `GitHubClient` (ABC), `RestGitHubClient` (REST v3), a
  provider-neutral exception hierarchy (`GitHubError` →
  `GitHubConnectionError` / `GitHubTimeoutError` / `GitHubAuthError` /
  `GitHubNotFoundError` / `GitHubRateLimitError` / `GitHubValidationError`), and
  frozen dataclasses at the boundary. Domain code never imports `httpx` and
  never sees raw provider JSON.
- `oauth.py` — the authorize URL, the code exchange, and token refresh.
- `__init__.py` — `get_github_client(token)`, returning `None` when the
  integration is unconfigured, exactly as `get_mail_client()` does.

Two details in the client that are easy to get wrong:

- **Pull requests are dropped at the seam.** `GET /repos/{owner}/{repo}/issues`
  returns PRs too, distinguished only by a `pull_request` key. Filtering there
  means no caller has to remember to.
- **A 403 is not always a permission error.** With `x-ratelimit-remaining: 0` it
  is a rate limit, which needs "wait", not "reconnect". They share a status
  code and are mapped to different exceptions.

Repository listing uses
`affiliation=owner,organization_member,collaborator` — the default would return
only owned repositories, and organization repos would silently never appear.

---

## 6. Deriving status

GitHub issues are `open` or `closed`. There is no "in progress". Ember shows
three lanes anyway, because a two-lane board is not useful:

| Lane | Rule |
|---|---|
| Open | open, no assignees |
| In progress | open, at least one assignee |
| Done | closed |

Assignment is the closest honest proxy for "someone picked this up". The UI says
so in the lane's tooltip rather than implying GitHub tracks it. Moving a card
updates GitHub directly: entering In progress assigns a user, Open clears
assignees, and Done closes the issue. The UI rolls an optimistic move back if
GitHub rejects it.

---

## 7. The OAuth callback

This is the one endpoint in Ember with no `Authorization` header: GitHub
redirects the *browser* to it, so `get_current_user` cannot run and something
else has to establish who is completing the flow.

That something is a signed state token (`ember/jwt.py:create_oauth_state_token`)
carrying `sub` (user id), `typ`, `provider`, a `jti` nonce, and a 10-minute
expiry. It is set as an httpOnly cookie **and** passed as the `state` query
parameter, and the callback requires all of:

1. both the cookie and the query parameter are present;
2. they are byte-identical (compared with `secrets.compare_digest`);
3. the token verifies, is unexpired, and was minted for this provider.

Only then is the code exchanged. The cookie is deleted immediately after use, so
a callback URL cannot be replayed.

`samesite="lax"`, not `strict`: the callback is a cross-site top-level GET from
github.com, which `lax` permits and `strict` would block — the same reasoning
already documented for the refresh cookie in `routers/auth.py`.

A signed token rather than an `oauth_states` table: its only job is to exist for
a few seconds, and a table for that would need its own cleanup job.

The token itself is never placed in a URL, a fragment, or a response body. On
success the user is redirected to `/settings?github=connected`.

---

## 8. Caching

Issue reads are cached in-process for 60 seconds, keyed by
`(user_id, repo_id, state, assignee, labels, per_page)`.

**Keyed by user, not just by repository** — two members of a workspace can have
different visibility on the same private repo, and one must never be served the
other's cached results. Creating an issue invalidates that repository's entries
so the new issue appears immediately rather than after the TTL.

In-process rather than Redis, because the codebase deliberately runs none
(Procrastinate is Postgres-native). The worst case of a cold cache is one extra
API call.

---

## 9. Partial failure

`list_workspace_issues` fetches repositories concurrently and collects failures
**per repository** into `repo_errors` rather than raising. A board with one
deleted, revoked, or rate-limited repository still renders the other four, and
the UI shows a dismissible banner naming what failed and why.

---

## 10. Endpoints

All workspace-scoped routes go through `assert_workspace_member`, and a
non-member gets **404, never 403** — consistent with the rest of Ember.

| Method | Path |
|---|---|
| GET | `/api/integrations/github/status` |
| GET | `/api/integrations/github/authorize` |
| GET | `/api/integrations/github/callback` |
| DELETE | `/api/integrations/github/connection` |
| GET | `/api/integrations/github/repos` |
| GET / POST | `/api/workspaces/{ws}/github/repos` |
| DELETE | `/api/workspaces/{ws}/github/repos/{repo_id}` |
| GET | `/api/workspaces/{ws}/github/repos/{repo_id}/labels` |
| GET | `/api/workspaces/{ws}/github/repos/{repo_id}/assignees` |
| GET / POST | `/api/workspaces/{ws}/github/issues` |

Everything that reaches GitHub depends on `_require_github_client`, so the whole
integration is testable against an in-memory double by overriding a single
FastAPI dependency — the same arrangement as the mail router's
`_require_mail_client`.

Disconnecting deletes the connection but leaves the tracked-repo rows: they are
workspace configuration, and another member's connection can still serve them.

---

## 11. Operator setup

1. Register an OAuth App at <https://github.com/settings/developers>, with the
   Authorization callback URL set to
   `<PUBLIC_APP_URL>/api/integrations/github/callback`.
2. Generate an encryption key:
   ```
   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
3. Set `GITHUB_OAUTH_CLIENT_ID`, `GITHUB_OAUTH_CLIENT_SECRET`,
   `GITHUB_TOKEN_ENCRYPTION_KEY` and `PUBLIC_APP_URL` (see
   `core/.env.example`), then restart the API.

`GITHUB_API_URL` / `GITHUB_OAUTH_BASE_URL` exist so a GitHub Enterprise Server
instance can be pointed at instead; they default to github.com.

Not set on the `worker` service: no background job touches GitHub.

---

## 12. Known gaps

- **No pagination.** The first page (up to 100 issues) per repository is shown.
  A repository with hundreds of open issues will be truncated.
- **No key rotation** (§4).
- **Assignee and label pickers are per repository**, reloaded on every change of
  target — correct, but an extra round-trip each time.
- **The `repo` scope is broader than this feature needs.** GitHub offers nothing
  narrower for OAuth Apps; a GitHub App would fix it, at the cost in §2.
