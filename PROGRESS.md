# Progress

## 2026-09-10: Production review remediation

- Closed cross-owner and cross-team writes for tasks, logistics, and
  SignalSeller customers, including manager scope, legacy forms, CSV-only
  shipments, aliases, retries, and concurrent PostgreSQL upserts.
- Unified the workbench to the T-1 six-store five-kit roster; confirmed empty
  sales batches now replace stale values with real zero, while failed refreshes
  preserve the last successful snapshot and mark it stale/N/A.
- Preserved every five-kit resubmission as an audit version, completed the empty
  response schema, and changed the home page to render each section as it arrives.
- Added an admin-only visual permission console for role/store/owner/team
  bindings. Its preview comes from the authoritative row-scope resolver, flags
  incomplete mappings, distinguishes dealer and read-only logistics access, and
  prevents the active administrator from locking out their own account.

Verification:

- Backend: `389 tests` passed in `52.255s`; final permission edge tests passed.
- Frontend: `8 tests` passed; Vue typecheck and production build passed.
- Python compilation, migration head/fresh upgrade, PowerShell deploy-script
  parsing, Docker Compose configuration, and `git diff --check` passed.
- Local image smoke test is pending because Docker Desktop's Linux engine pipe
  was unavailable; no production deployment was attempted from this worktree.

## 2026-09-09: September targets and T-1 five-kit scope

- Set the confirmed September sales targets to Lina 400 万, 尤文静 100 万,
  何海文 95 万, 杨晶晶 333 万, 于冰 200 万, and a pooled 100 万 for the new
  department (陈鹏飞、李浩然、邢哲夫), with a validated department total of
  1,228 万.
- Restricted daily five-kit completion to Dar Al Sabaek, Safiran Hamrah, and
  the four VMG Vietnam stores. Reports use the previous Shanghai calendar day.
- Aligned the required-store owner keys with active production identities:
  Dar/Safiran use Viki; all four VMG stores use Ivan.

Verification:

- Backend: `372 passed`, `5 skipped`, `31 subtests passed` in `99.55s`.
- Focused target/store tests: `21 passed`, `2 subtests passed`.
- Frontend: `6 passed`; Vue typecheck and production build passed.
- Python compilation, Docker Compose validation, and `git diff --check` passed.
- Read-only production check: all six required stores and six bound dealer
  accounts are active; 2026-09-08 has five required submissions, with Safiran
  Hamrah missing.

## 2026-09-08: PDCA production hardening

- Corrected five-kit completion and daily-report metrics so only required stores
  contribute to the denominator and reported count; missing or invalid sales
  targets now degrade to `N/A` instead of producing invented completion rates.
- Applied one authoritative row-level owner/team scope to todo projects, tasks,
  replies, exports, reminders, and group notices. Mixed-team projects fail closed.
- Odoo/VPS SSO now unlocks legacy seeded users after verified identity while
  rotating their local password and password version, so old defaults stay invalid.
- Added durable daily-report delivery claims, separate alert routing, disabled
  unfinished scoring/ledger schedules by default, and made ledger dry-runs free
  of database, document, or messaging writes.
- Repaired the Alembic revision chain, added delivery-safety schema migration,
  and made remote deployment migrate a tested candidate image after database
  backup and before cutover.

Verification:

- Backend: `367 tests` passed in `45.619s`; Python compilation passed.
- Frontend: `6 tests` passed; Vue typecheck and production build passed.
- Migrations: one head (`010`); fresh, historical-unversioned, and runtime-built
  database upgrades all reached `010 (head)`.
- Container: final local candidate `sha256:ecf9607d9821...` passed SQLite smoke
  tests with revision label `working-tree-20260908-final`.
- PostgreSQL: login/password change, upsert/zero overwrite, owner isolation,
  cross-owner/admin denial, SPA assets, and outage-to-HTTP-503 checks passed.
- Production cutover completed at exact SHA `9faa04842f5845d2556d7d9d6a7a6a7332eb2d65`:
  PostgreSQL backup and migration succeeded; public health, login, SPA assets,
  six key browser routes, core counts, and zero browser-console business errors
  were verified after deployment.

## 2026-09-07: Knowledge access security remediation

- Preserve disabled SSO identities and invalidate sessions on deactivation.
- Separate access and step-up JWT purposes; bind exports to the active login
  and revoke step-up state on logout.
- Validate browser write origins, retaining same-origin native forms through
  a same-origin Referrer-Policy without allowing opaque/cross-site origins.
- Use safe evidence rendering, version-pinned previews and the complete
  reauthentication/grant/download protocol in the knowledge UI.
- Verification before main integration: 59 focused offline backend tests,
  three Chromium scenarios, Vue typecheck and isolated frontend build passed.
  Independent review found no remaining runtime P1/P2 in the changed paths.
- Companion datahub and production cutover remain separate release gates.

## 2026-09-03: Authenticated dealer knowledge MCP

- Added a Streamable HTTP MCP endpoint at `/mcp/` to the PDCA workbench.
- Added read-only tools for visible dealers, cited evidence search, and evidence-based answers.
- Reused PDCA bearer authentication, password-version revocation, dealer scope, data-hub service tokens, redaction, and retrieval audit.
- Kept the human knowledge page at `/app/knowledge`; browser and AI access share the same authorization boundary.

Verification:

- Backend: `234 passed, 5 skipped`; the skips require a built SPA artifact.
- MCP transport: missing bearer token returns `401`; valid scoped token lists three tools.
- Sales scope: assigned dealer succeeds and an unassigned dealer returns `403` before the data-hub call.
- Python compilation and Docker Compose configuration validation passed.

## 2026-08-22: Dealer knowledge hub pilot

- Added the `/app/knowledge` entry for human evidence search and cited AI answers.
- Added same-origin PDCA proxy APIs with five-minute scoped service tokens.
- Added dealer UUID mapping, team mapping, role enforcement, and admin-only original export.
- Kept Safiran Hamrah under 尤文静 and deduplicated VMG branches into one knowledge dealer.
- Configured 刘春梅 as overseas team manager and 尤文静 as self-scoped sales; neither can export originals.
- Added upload, high-sensitivity review, password step-up, and one-time original download to the formal page.
- Added production Compose key-file mounting and an operations acceptance runbook.

Verification:

- Backend: `173 tests` passed; Python compilation passed.
- Frontend: `vue-tsc --noEmit` and Vite production build passed.
- Docker Compose production configuration passed with disposable validation values.
- Real local PostgreSQL/data-hub path: search, watermarked preview, sales export `403`, admin export `200`.
- Playwright desktop and `390x844`: 8 results, 8/8 images loaded, first result `image12.png`, zero console errors, no horizontal overflow.

Cloud PostgreSQL pilot data is active. OSS credentials and bucket remain a deployment gate; application cutover requires the immutable image, Redis/shared key runtime, and health checks to pass.
