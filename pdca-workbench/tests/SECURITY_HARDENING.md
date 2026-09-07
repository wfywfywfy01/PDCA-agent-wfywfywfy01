# PDCA security hardening verification

Scope: PDCA identity, browser writes, knowledge rendering, versioned previews,
and original-export sessions. No schema changes, production configuration changes,
datahub edits, deployment, dependency installation, or production login.

## Backend replay

From `pdca-workbench`, with the installed Python dependencies:

```powershell
python -B scripts/test_security_offline.py
```

The runner clears application environment variables, disables both dotenv loaders,
uses temporary/in-memory SQLite, and rejects `.env` reads, repository writes,
non-test SQLite, PostgreSQL connections, external sockets, and child processes.
Windows asyncio's internal socketpair is the only allowed socket connection.
It does not start the application lifespan, scheduler, or production services.

Default selection: 59 tests (49 existing tests plus 10 new hardening tests):

| Module | Count | Selection |
| --- | ---: | --- |
| `tests.test_knowledge_integration` | 11 | All |
| `tests.test_knowledge_mcp` | 4 | All except `test_session_manager_survives_multiple_app_startups` |
| `tests.test_odoo_sso` | 12 | All |
| `tests.test_security` | 15 | Exact name filters below |
| `tests.test_auth_write_flows` | 7 | Exact name filters below |
| `tests.test_auth_hardening` | 10 | All |

`test_security` name substrings: `scope_`, `unconfigured_sales`, `dealer_is_`,
`non_dealer_`, `proxy_role_header`, `security_headers`, `login_copy`,
`resolve_file_under`, `view_path_rejects`, `encoded_traversal`.
Exclude `test_empty_customer_scope_returns_one_row_per_grade`, which needs the
legacy business module deliberately unavailable in the empty temporary repo.

`test_auth_write_flows` name substrings: `login_success`, `logout_revokes`,
`public_vps_probe`, `forced_password`, `representative_role`, `deactivate_dealer`,
`sales_accounts_cannot`.

The verbose runner prints every selected test ID. This is a focused regression
suite, not a claim that the complete PDCA suite passed.

Minimal offline repro/regression commands (each uses the same safety guard):

```powershell
python -B scripts/test_security_offline.py tests.test_auth_hardening
python -B scripts/test_security_offline.py tests.test_auth_hardening.AuthHardeningTests.test_all_sso_entries_reject_inactive_user_without_mutation
python -B scripts/test_security_offline.py tests.test_auth_hardening.AuthHardeningTests.test_reauth_is_bound_to_login_and_revocation_is_enforced
python -B scripts/test_security_offline.py tests.test_auth_hardening.AuthHardeningTests.test_csrf_sources_and_no_forged_bearer_bypass
```

The new suite also covers disable/re-enable token invalidation, special-purpose
JWT rejection in HTTP and MCP, logout cookie deletion/revocation, source-less
forms, same-origin/Referer writes, TLS termination, Bearer CLI, and optional UUID
preview-version forwarding. SSO coverage includes proxy headers, localhost VPS,
ticket SSO, and URL-session SSO. Both browser SSO routes call
`finish_odoo_sso_login`, whose `_set_pdca_cookie(..., framed=True)` remains intact.

## Frontend replay

From `apps/web`, use existing `node_modules`; do not invoke the normal Vite config
for this offline check because it loads environment files.

```powershell
node node_modules/vue-tsc/bin/vue-tsc.js --noEmit -p tsconfig.json
@'
const allowed = new Set(['PATH','SystemRoot','SYSTEMROOT','WINDIR','COMSPEC','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA']);
for (const key of Object.keys(process.env)) if (!allowed.has(key)) delete process.env[key];
const {build} = await import('vite');
const {default:vue} = await import('@vitejs/plugin-vue');
const path = await import('node:path');
await build({configFile:false,envFile:false,root:process.cwd(),base:'/',plugins:[vue()],resolve:{alias:{'@':path.resolve('src')}},build:{outDir:'dist',sourcemap:false}});
'@ | node --input-type=module -
```

Then from `pdca-workbench`:

```powershell
python -B tests/test_knowledge_frontend.py
```

Two Playwright tests use a fresh Chromium profile and intercept every page request:
only local synthetic responses for `ui.invalid` are served; all other requests
are aborted. Screenshots/downloads use a temporary directory, never Git.
Checks: literal malicious titles with no event attributes or script execution,
version-pinned preview URLs, 1280/390px layouts without horizontal overflow,
legacy export and Vue password-failure retry followed by reauth/grant/download.
This checks PDCA UI/protocol behavior, not datahub pixel/PDF redaction.

## Compatibility and retained controls

- Existing SSO accounts keep administrator-controlled inactive status. Rejected
  identities are not synchronized or issued a new login cookie.
- Disabling an active account increments `pwd_version`; re-enabling it does not
  revive old login or step-up tokens.
- Generic login JWTs must have no `purpose` claim. Old step-up cookies lacking
  `login_jti` are intentionally rejected; verify the password again.
- Step-up requires the current login JWT. Proxy-only sessions must obtain the
  normal cookie through `/api/auth/vps-bootstrap` before original export.
- Cookie writes require a matching Origin, or Referer when Origin is absent.
  Fetch-Metadata cannot override a missing/foreign source. Same-origin forms and
  fetch from a same-origin iframe document work. A frame ancestor is not a
  trusted write origin; cross-origin parent submissions remain denied.
- Bearer CLI requests without cookies/browser headers continue to work. Scripts
  intentionally using cookie authentication must send a trusted Origin/Referer.
- TLS-offloaded HTTPS is supported by the configured workbench URL and the
  current host when secure cookies are enabled, not arbitrary forwarded headers.
- `asset_version_id` is an optional UUID. Omitting it preserves current-version
  behavior; pinned citations require the companion datahub version-aware route.
- Existing protections remain: explicit sales/dealer/team mapping, empty scope
  denial, rejection before upstream calls, read-only upload denial, administrator
  checks for mapping changes/sensitive review/original export, fresh password
  verification, forced-password-change gating, and MCP scope enforcement.

Compose/deployment checks and production end-to-end tests are intentionally not
run for this user-scoped task. No production permissions or data were changed.
