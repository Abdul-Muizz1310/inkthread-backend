# 12 · Platform token (contract v2)

Every route except the public ones needs a platform token: a 60-second Ed25519 JWT minted by bastion
or by inkthread-frontend's server (DR-0030). This is inkthread's copy of the portfolio's platform
contract v2; the other backends implement the same rules in their own code.

## 1. The token

A compact JWS in `X-Platform-Token` (or `Authorization: Bearer`, read second), `alg` `EdDSA`:

| claim | value |
|---|---|
| `iss` | `"bastion"`, or `"inkthread-frontend"` |
| `aud` | `"inkthread"`, a string (a list is refused) |
| `sub` | bastion: a visitor pseudonym or `"bastion"`; the frontend: `"inkthread-frontend"` |
| `role` | bastion: `viewer` / `editor` / `admin` (not checked here); the frontend: `"frontend"` |
| `iat`, `exp` | integers; `exp - iat <= 300` |
| `service`, `cap`, `jti`, header `kid` | informational; never trusted |

## 2. Verification

`inkthread.platform.token.verify` is pure: a token, the trusted keys and the time in, a `Principal`
`{iss, sub, role}` or `TokenRejected(check)` out. A token is accepted iff:

1. it parses as a compact JWS whose header names `alg: EdDSA` (`none`, `HS256` and the rest are refused
   before any key is tried);
2. its signature verifies against a trusted key, and that key allows its `iss`:
   - bastion's key (`BASTION_SIGNING_KEY_PUBLIC`, base64 SPKI DER, or `BASTION_PUBLIC_KEY_URL`'s JSON
     field `publicKey`, fetched and kept for an hour) allows `iss: "bastion"`;
   - the frontend's key (`INKTHREAD_FRONTEND_SIGNING_KEY_PUBLIC`) allows `iss: "inkthread-frontend"`
     with `role: "frontend"`.
   The key decides the issuer: a frontend-signed token that claims `iss: "bastion"` is refused;
3. `aud == "inkthread"`;
4. `exp` and `iat` are integers, `exp + 10 > now`, `iat - 10 <= now` (10 s leeway), and
   `0 < exp - iat <= 300`;
5. `sub` is a non-empty string.

A key value that is not base64 Ed25519 SPKI DER fails the boot (spec 10: a bad configuration fails
the boot, not the first request).

## 3. The middleware

A pure ASGI middleware inside CORS (so its refusals carry CORS headers and event streams pass through
untouched):

| case | answer |
|---|---|
| a public route: `/health`, `/version`, `/metrics` (its own bearer), `/docs`, `/docs/*`, `/redoc`, `/openapi.json` | passes, token or not |
| no trusted key configured, outside `APP_ENV=test` | `503 platform_auth_unconfigured` (fail closed) |
| no token, `DEMO_MODE=false` (the default) | `401 missing_platform_token` |
| no token, `DEMO_MODE=true` | proceeds anonymous; a WARNING is logged |
| a token that fails any check | `401 invalid_platform_token`, whatever `DEMO_MODE` says; a WARNING names the check, never the token |
| a valid token | proceeds; `request.state.principal` holds `{iss, sub, role}` |

Refusals use the envelope with `detail` set to the code: `{"error": "invalid_platform_token",
"message": "…", "detail": "invalid_platform_token"}`. Under `APP_ENV=test` with no key the middleware
lets every request through anonymous, so tests that are not about the token need none.

- **Admin routes** need a valid platform token **and** `X-Admin-Token`, as before (spec 07).
- **Uploads' rate limit** keys on `"bastion:{sub}"` for a bastion token (the visitor pseudonym), on
  `"inkthread-frontend:{client address}"` for a frontend token (its `sub` is constant, so keying on it
  would put every visitor of the site in one bucket), and on the client address without a token.
  The client address is the leftmost `X-Forwarded-For` as uvicorn's proxy headers apply it behind
  Render: the proxy forwards exactly one address it sets itself, and a direct browser upload's is the
  visitor's own. *(Amended 2026-10-20: the first draft keyed every token on `iss:sub`.)*
- **CORS** allows the request headers `content-type`, `x-admin-token`, `last-event-id`,
  `x-platform-token` and `x-request-id`.

## 4. Test cases (the contract's conformance list, 1–14)

- T-PT-1 A valid bastion token with `aud: "inkthread"` is accepted.
- T-PT-2 `aud` naming another service is refused.
- T-PT-3 A missing `aud` is refused; an `aud` list (even one holding `"inkthread"`) is refused.
- T-PT-4 `iss: "bastion"` signed with the frontend key is refused (and the reverse).
- T-PT-5 A frontend-key token whose `role` is not `frontend` is refused.
- T-PT-6 Expired 5 s ago is accepted; expired 15 s ago is refused.
- T-PT-7 `iat` 5 s in the future is accepted; 15 s in the future is refused.
- T-PT-8 `alg: none` and `alg: HS256` (signed with the public key's bytes) are refused.
- T-PT-9 A tampered payload is refused.
- T-PT-10 No token with `DEMO_MODE=false` → 401 `missing_platform_token`; with `DEMO_MODE=true` the
  request proceeds and a WARNING is logged.
- T-PT-11 A present but invalid token with `DEMO_MODE=true` → still 401 `invalid_platform_token`.
- T-PT-12 No trusted key outside the test settings → 503 on a protected route, 200 on `/health`.
- T-PT-13 Every public route answers without a token; no write is public.
- T-PT-14 The rate-limit key is `bastion:{sub}` for a bastion token and
  `inkthread-frontend:{client address}` for a frontend token: two visitors through the frontend (two
  client addresses) land in different buckets, one visitor's frontend and bastion uploads in
  different buckets, and two bastion subjects from one address in different buckets.

Beyond the contract:
- T-PT-15 `exp - iat` over 300 s, a non-integer `exp`, an empty `sub`, and an unsigned or malformed
  token are refused; a WARNING names the failed check and not the token.
- T-PT-16 Admin routes need both the platform token and `X-Admin-Token`.
- T-PT-17 A bastion key from `BASTION_PUBLIC_KEY_URL` verifies, and is fetched once an hour at most;
  a key value that is not Ed25519 SPKI DER fails the settings.
- T-PT-18 The CORS preflight allows `x-platform-token` and `x-request-id`; a 401 carries the CORS
  headers for an allowed origin.
- T-PT-19 The event stream through the middleware still arrives event by event, and the reading,
  graph and page image need the token like every other read.
