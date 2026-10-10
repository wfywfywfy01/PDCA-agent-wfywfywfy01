# Progress

## 2026-10-10: Omega Doubao pause and resume recovery

- Fixed the provider-side cause of the phone pause failure: cancelling/committing/muting the native Doubao ASR connection could create an input identity without a final transcript. Doubao recorder pause now sends exact-zero 16 kHz PCM continuously, blocks browser microphone PCM and opponent output locally, and drains all accepted public speech before reopening the microphone on resume. Stop uses the same natural VAD drain. No provider reset or instruction update is sent for these controls.
- Preserve delayed public ASR hypotheses and identity-only final events without inventing speech; validate the active owner/lease before closing an empty final. Old finals cannot certify fresh resumed PCM, and late old replies remain blocked. A failed zero-PCM sender fails the session even if the provider closes normally or the request is cancelled.
- Test-first evidence: the original handler failed both zero-stream acceptance regressions; removing the reviewed protections caused all five initial race regressions to fail. The final suite includes six dedicated pause race/error regressions. Full backend discovery: **1,095 tests, OK, 11 PostgreSQL-dependent skips**, 223.423 seconds. Frontend **23/23** tests, typecheck/build, isolated mobile UI acceptance, Compose configuration, Python compilation and `git diff --check` passed. CI remains the required PostgreSQL/image gate.
- Real provider application integration used the current `VoiceControl`, sender and receiver against disposable SQLite and synthetic speech, with server-local credentials. Partial speech -> 78-second pause -> resume -> two further rounds -> stop passed: **3 sales finals, 2 opponent finals, 5 durable segments, 928,822 output PCM bytes, 0 private PCM leaks, 0 uncompleted ASR identities, succeeded job**. Independent pure-provider probes also passed partial-speech and in-progress-opponent pause, including 78 seconds. These tests do not establish physical microphone or human listening quality.
- Evidence and no-secret probe helpers: `D:/Vertu/data/excel/26年数据/10月/部门工作画像/督战官文件/Omega_暂停恢复修复_2026-10-10/`. Production deployment and physical-phone post-deploy checks follow the reviewed main commit and immutable image; no credentials or browser artifacts are tracked.

## 2026-10-10: Omega phone control failure states

- Based on production `97aad040baf028d333fec3581cd4a24442210938` in isolated branch `codex/omega-phone-control-errors`. Frontend failures now enter an explicit error phase, stop playback and PCM forwarding, clear pending control/timers, and keep hangup available. Only an error matching the current request key may bypass the lower-epoch filter; the epoch never rolls back. A timeout rejects late success ACKs instead of remaining in `resuming`.
- Known incomplete-tail errors disable recovery on the current connection and instruct the seller to end the call, check the transcript and start a new practice. Failure no longer displays the private coach as ready. Report completion updates the stale generating notice to the saved-result notice.
- Fresh verification: the expanded real Vue/mobile browser regression failed against the original production frontend, then passed after the fix. It covers matching older-epoch error, timeout, late success, stale spontaneous error, fatal-tail recovery denial, paused microphone, normal recovery and hangup cleanup, and the report notice. APIs/database are isolated and real; voice WebSocket/audio are synthetic substitutes. `npm test` passed 23/23; `npm run typecheck`, `npm run build` and `git diff --check` passed. Logs and mobile screenshots are under `D:/Vertu/data/excel/26年数据/10月/部门工作画像/督战官文件/Omega_手机控制错误修复_2026-10-10/`.
- No backend voice logic, persisted tail/job state or report guard was changed. No production deployment, merge, physical-phone or provider-content validation was performed for this frontend candidate; the underlying production pause-tail defect remains unresolved.

## 2026-09-29: Omega Doubao live voice cutover and transcription repair

- After the `volc.speech.dialog` grant, deployed commit `a6ec5a6a8f52277e8ff79405a60eedb859e91f00` with `PDCA_OMEGA_REALTIME_PROVIDER=doubao`; the same production container uses `https://api.deepseek.com` / `deepseek-flash` for text. A dedicated SSH Docker account now carries deployment secrets instead of the unauthenticated TCP 2375 transport. Public `/health` returned 200 at that revision; Web and Omega worker were running.
- A real 16 kHz synthetic Chinese speech clip sent from the production container produced a completed input transcription, a text reply, and 298,558 PCM output bytes. This exposed a provider event mismatch: Doubao puts the final sales transcription in `text`, while the adapter read `transcript`. The adapter now accepts the actual `text` field and retains the older fallback. A regression test with the real event shape failed before the fix and passed after it.
- Patched application WebSocket acceptance with the same real provider and speech clip returned `ready`, 26 live captions, two persisted sales/counterparty segments and 326,714 forwarded audio bytes, with no error event. Full backend: **915 passed, 6 skipped, 47 subtests passed**; frontend typecheck/build, Compose config and `git diff --check` passed. Physical phone microphone, headset echo, interruption timing and long-session stability still need device acceptance.

## 2026-09-29: Omega natural-language case intake

- Replaced the new-case form entry with one free-text description and `AI 分析`. The authenticated server uses the already configured `qwen-audio-3.1-realtime-plus` connection in text-only mode (or the configured supervisor text model) to extract a reviewable case draft. It does not write a case during analysis. Missing goals, dates, amounts and hard limits stay missing; the UI lists gaps and lets the seller add detail or expand the editable fields before saving. Existing cases retain manual editing and confirmed-version rules.
- Evidence: a live fictional text-only Qwen call returned structured JSON with the stated 10,000 USD amount, 2026-10-05 date and no invented missing values. The authenticated local `/api/omega/case-draft/analyze` endpoint returned 200 with those fields. A real Chromium browser clicked `AI 分析`, displayed the draft, found no missing fields for the complete fictional example, exposed the filled amount/date/limit fields on review, and had zero page errors or mobile horizontal overflow. Focused Omega flow and realtime suites: **30 passed**. Frontend: **8 passed**, typecheck/build passed; browser API smoke and simulated Practice + Perform walkthrough passed. The scheduled local service was restarted on the final code and `/health` returned 200.
- Report generation remains a separate text-model-and-worker capability; analysis alone does not enable it.

## 2026-09-29: Omega training UI rebuild

- Reworked Omega around the training flow: a compact task/assignment/history navigator, a clear target summary, readable two-sided transcript, and a prominent realtime voice control. Recent history shows five records by default, with access to all records. Text controls appear only when the text model is ready; manager assignment and meeting import are collapsed until opened.
- Kept the existing PDCA visual tokens and all authenticated workflows. Tightened desktop navigation so the full menu stays on one row at 1365 px; mobile keeps the menu button and shows the full transcript without an inner scroll.
- Evidence: Vue typecheck, 8 frontend tests and production build passed. Browser smoke passed case creation/confirmation, delayed microphone cancellation, realtime PCM/interruption/hangup/reconnect, text turn, report and review at desktop and 390 px. The running localhost app was checked at 1365 and 390 px: zero page errors or horizontal overflow; desktop navigation height 50 px. Screenshots: `%LOCALAPPDATA%/VertuOmega/local/omega-final-home.png`, `omega-final-desktop.png`, `omega-final-mobile.png`.

## 2026-09-29: Omega local service and two-turn browser acceptance

- Registered `VertuOmegaLocal` as a Windows logon task so the isolated localhost service survives the Codex process ending. The launcher keeps its session signing secret in local AppData and writes server logs there. It still binds only `127.0.0.1:8769` and reads the supplied Qwen credential file at startup.
- Fixed immediate voice reconnect: authenticated, owner-scoped `POST /api/omega/sessions/{id}/realtime/stop` releases the current stream lease; the browser waits for confirmation after stopping microphone and playback, then enables reconnect. Removed temporary diagnostic routes from the local launcher.
- Fresh evidence after restarting the scheduled task: `/health` and `/app/omega` returned 200; local login and `/api/omega/status` returned 200; the removed provider probe route returned 404. Focused realtime suite: **10 passed**; Vue typecheck, production build, Python compilation and `git diff --check` passed. A real Chromium browser using synthetic speech completed two Qwen voice turns, stopped the microphone track after each hangup, reconnected, froze and reloaded four persisted segments (sales/counterparty/sales/counterparty), received **1,378,560 audio bytes**, and reported zero page or WebSocket errors. Screenshot: `%LOCALAPPDATA%/VertuOmega/local/acceptance.png`.
- The supplied key remains voice-only for this app: text model calls returned 403 previously, so report generation still needs a chat-enabled model key and worker. Human microphone/headset, longer stability and production deployment remain unverified.

## 2026-09-28: Omega independent localhost trial

- Added `scripts/run_omega_local.py` to read the supplied Qwen credential file at process startup, bind an isolated development app to `127.0.0.1:8769`, and create an isolated SQLite database and local manager login under `%LOCALAPPDATA%/VertuOmega/local`. No provider secret is written to the repository or local login file. Existing services on ports 5183 and 8767 were left running.
- Fresh live evidence: frontend production build passed; `GET /health` returned 200 with connected SQLite; local login, authenticated Omega status, and built `/app/omega` page returned 200. Chromium completed browser login and showed the confirmed fictional trial case with no page errors. With synthetic, non-customer SAPI speech through the real browser capture pipeline and authenticated WebSocket, Qwen returned 380,160 audio bytes, live captions, no WebSocket/page errors, and the server persisted one sales and one counterparty final segment.
- The supplied key lists `qwen3.5-plus` and `qwen-plus` but denies chat-completions requests with HTTP 403 `Access denied by API-Key restrictions`. This local trial has real voice but no text worker or report generation until a chat-enabled key is supplied. Human microphone, echo cancellation, and production deployment remain unverified.

## 2026-09-28: Omega Qwen realtime speech integration

- Replaced the unprovisioned Doubao dialogue transport with Alibaba Cloud Model Studio `qwen-audio-3.1-realtime-plus` in Beijing. The server now authenticates with a workspace ID and API Key, sends 16 kHz PCM16 over the model's WebSocket event protocol, and returns 24 kHz PCM16 plus final transcripts to the authenticated Omega browser session. The browser playback decoder now matches PCM16.
- Kept the existing one-stream lease, team/source checks, frozen transcript rules and secret boundary. Interrupted or cancelled model responses do not become report evidence. No credential from the user-provided `qwen.env` was copied into source, docs or tracked configuration.
- Live provider evidence with the supplied key and a synthetic, non-customer voice clip: `session.created`, `session.updated`, user transcription, completed assistant response, assistant transcription and 145,920 output audio bytes. A second synthetic clip sent during assistant speech produced `cancelled` then `completed` responses with no provider error; the model handled the interruption itself. The authenticated application WebSocket path, against disposable SQLite and the live provider, persisted one sales and one counterparty segment and forwarded 334,080 audio bytes without an error.
- Regression evidence: full backend `python -m pytest -q --disable-warnings` returned **786 passed, 6 skipped, 31 subtests passed**; focused realtime suite **9 passed**, including reconnect context restoration. Frontend **8 passed**, typecheck and production build passed; Chromium browser smoke passed PCM16 playback, interruption, hangup, text fallback and report/review. Compose validation passed with disposable placeholder variables and confirmed both new variables reach only the Web container; source scan found zero copies of the supplied API Key.
- Real microphone/headset echo, live user interruption timing, 30-minute stability, production reverse proxy, actual Vemory data and scoring calibration remain unverified. The browser-memory demo remains simulated; no production release was made.

## 2026-09-28: Omega Practice＋Perform linked pilot

- Added buyer profile and nine configurable score weights to immutable case versions. `rubric-v2` report generation and validation use the frozen weights and still reject fabricated quotes or unsupported scores.
- Added migration `016`, team-scoped assignments, source-report authorization, targeted dimension/pass threshold, repeated attempts and evidence-based progress. A Vemory real-review report can drive an assignment only for a seller with access to that source. New practice sessions retain the assigned case version after later edits.
- Added manager assignment and seller retry views, source baseline comparison, and an explicitly simulated Practice＋Perform walkthrough to `npm run demo`. Fixed the shared request validation handler so model-validator errors return JSON 422 instead of raising a 500; refreshed assignment status after report completion.
- Evidence: disposable local PostgreSQL upgraded `015` to `016`; focused SQLite/realtime/PostgreSQL suite **34 passed**. Full backend `python -m pytest -q --disable-warnings`: **786 passed, 6 skipped, 31 subtests passed**. Frontend **8 passed**, typecheck and production build passed. Browser API smoke and browser-memory Practice＋Perform walkthrough passed; `git diff --check` passed. Real Doubao, real Vemory data, human scoring calibration and production cutover remain unverified.

## 2026-09-28: Omega runnable interaction prototype

- Added `npm run demo` in `apps/web`, serving the real Omega page at `http://127.0.0.1:5183/omega` with browser-memory fixtures. The demo has a visible label, a seeded negotiation case, editable cases, simulated text turns, a sample report, manager review and a local PCM voice interaction. It does not proxy `/api` traffic to PDCA or call Doubao, and resets on refresh.
- Chromium checks passed for the seeded text flow, new case/confirmation/review, and simulated realtime PCM/caption/response/hangup. Frontend `npm test` (8 passed), `npm run typecheck` and production `npm run build` passed. This verifies the runnable prototype, not live provider quality.

## 2026-09-25: Omega continuous realtime speech stream

- Added a same-origin authenticated WebSocket that proxies Doubao's binary dialogue protocol. App ID and Access Key stay on the server. The browser captures continuous 16 kHz PCM, plays 24 kHz PCM chunks, clears queued speech on interruption and stops microphone tracks on hangup, session switch, finish or unmount.
- Added a database-backed one-stream lease, migration `015`, final sales/counterparty transcript persistence, active-session/source-permission checks and cancellation of competing text turns. Status now reports text and realtime readiness separately; reports still require the text model and worker. Added the two realtime variables to `.env.example` and independent-operation steps to `omega-v2-operations.md`.
- Verification: full backend `python -m pytest -q --disable-warnings`: **784 passed, 6 skipped, 31 subtests passed**. Focused realtime tests: **9 passed** including actual login Cookie, SPA microphone policy and mocked provider audio/text. Disposable local PostgreSQL upgraded from `014` to `015`; **6 PostgreSQL tests passed**, including realtime lease/frozen-session behavior. Frontend: **8 tests passed**, `typecheck` and production build passed. Chromium mock flow passed continuous PCM capture, audio response, interrupt, hangup/disconnect track cleanup, text fallback and report/review flow at desktop and 390 px. Compose configuration and `git diff --check` passed.
- The user has not opened the Doubao end-to-end speech service. Live provider handshake, device echo/latency, production reverse proxy, real customer quality and deployment remain **unverified**; simulated events are engineering checks only.

## 2026-09-24: Omega v2 functional self-check

- Corrected Vemory import deduplication so the same transcript and goal in two
  cases cannot return a session from the other case. An existing import is
  checked against the current case and source permission before returning it.
- Re-read and lock the case after the Vemory fetch. A draft changed while the
  external request runs now blocks import until the new goal is confirmed.
- Re-check source authorization after model generation and before saving a turn
  or report. A permission revoked during the model call now fails the job.
- Refresh the locked session row when submitting a turn or ending a session.
  A request that read `active` before another transaction ended the session
  now receives 409 and cannot append to the frozen transcript.
- Cancel a pending microphone permission request on session switch or finish;
  close the associated audio context and stop late audio tracks.

Verification: each backend regression above failed before its fix and passed
afterward. Omega SQLite flow: 17 tests passed; disposable local PostgreSQL:
5 concurrency/lease tests passed. Full backend: `Ran 778 tests in 87.318s`,
`OK (skipped=5)` (PostgreSQL cases run separately). Frontend: 8 tests,
typecheck, production build, and Chromium browser smoke including delayed
permission and active recording cancellation passed. Real model, ASR device, live Vemory data,
load/latency and deployment remain unverified.

## 2026-09-24: Omega v2 local implementation

- Implemented the authenticated PDCA Omega module on `codex/omega-v2`: team-scoped
  cases, confirmed immutable target versions, isolated sessions, PostgreSQL-backed
  jobs with lease recovery and partial unique indexes, actor/coach separation,
  quote-checked reports, manager reviews, worker heartbeat and readiness.
- Added the Vue text flow, optional protected 30-second WAV transcription with
  user correction and stored original transcript, browser TTS, and Vemory import
  requiring source scope and complete speaker mapping. Post-meeting goals cannot
  receive an achievement score. The Web app and `omega-worker` run without Codex.
- Added frozen migration `014`. Fixed older `008` and `013` Boolean defaults that
  prevented a fresh PostgreSQL upgrade. All eight Omega tables use aware UTC
  timestamps. A disposable PostgreSQL 16 cluster reached `014` from an empty
  database; table columns and expected indexes matched the model metadata.
- Added `pdca-workbench/docs/omega-v2-operations.md` for independent operation,
  environment variables, checks and release boundaries. No production service,
  external model, ASR provider or Vemory source was called in this milestone.

Verification:

- Full backend: `python -m unittest discover -s tests -q` returned
  `Ran 774 tests in 100.441s`, `OK (skipped=4)`.
- Omega API/worker: 14 focused SQLite cases passed; 4 isolated PostgreSQL cases
  passed for claim exclusivity, concurrent turn submission, end/reply order and
  expired-lease recovery. One standalone worker process wrote a heartbeat to the
  test PostgreSQL database.
- Frontend: `npm test` 8 passed; `npm run typecheck` and `npm run build` passed.
  Playwright Chromium completed create -> confirm -> turn -> report -> manager
  review at 1280px and checked the 390px view with no horizontal overflow or
  browser errors. `docker compose --profile omega config --quiet`, Python
  compilation and `git diff --check` passed.
- Live model behavior, microphone/ASR quality, real Vemory field compatibility,
  latency/load, production cutover and old public API closure remain unverified.
  The isolated worktree has no `.env`; credentials must be placed in deployment
  secret storage before those checks. This is not a production release. The
  temporary PostgreSQL process was stopped; automatic approval review blocked
  recursive deletion of its test-only data directory, so the directory remains
  under `D:\cdoeX-work\omega-pg-test-b530bb4fd79643c29121c72c53462535`.

## 2026-09-24: Omega v2 architecture proposal

- Confirmed scope with the user: architecture and implementation plan only;
  sales and supervisors train together, with team visibility by default.
- Added `vertu-omega/docs/2026-09-24-architecture-v2.md` and
  `docs/superpowers/plans/2026-09-24-omega-v2.md` after inspecting the Omega
  prototype and the existing PDCA auth, scope, database, model, knowledge,
  meeting and Vue modules at commit `73d5588`.
- Proposed versioned goals, separate actor/coach context, durable isolated
  sessions, evidence-checked reports, supervisor calibration, and staged
  voice/actual-meeting integration. These are planned capabilities, not
  implemented behavior or measured performance.
- Added `vertu-omega/docs/2026-09-24-acceptance-and-test-protocol.md` with
  explicit correctness cases, proposed performance/quality gates, isolated
  PostgreSQL/browser procedures, and required evidence. Reused script paths
  were checked against the current repository; no acceptance scripts were run.
- Corrected the planned commit conditions: turns require active sessions,
  reports require ended sessions with matching frozen inputs. Added a partial
  unique index requirement for concurrent turns and a consistent lock order.

Verification: UTF-8 decoding, Markdown fence balance, local document links,
trailing whitespace and plan placeholder checks. No application code,
production state or business records changed; no runtime tests were run for
this documentation-only milestone.

## 2026-09-16: Logistics operations console same-origin mount

- Added `/logistics-admin/...` as a server-side proxy to the independent
  `logistics-track` operations console.
- PDCA authentication and role gates run before forwarding; dealer accounts are
  blocked, manager/admin writes are allowed, and only logistics session cookies
  are sent upstream. Upstream sessions, CSRF and audit records remain owned by
  `logistics-track`.
- Added an embedded operations panel and new-window link to `/app/logistics`.
- Added `PDCA_LOGISTICS_ADMIN_UPSTREAM` and timeout configuration to Compose and
  the remote deployment script. Empty configuration keeps the original board
  available and returns a clear `503` for the optional console.

Verification:

- Backend: full PDCA suite `329 passed`; proxy-focused suite `9 passed`.
- Frontend: `npm test` (6 passed), `npm run typecheck`, and `npm run build` passed.
- Docker Compose configuration and `git diff --check` passed with disposable
  validation values. Live upstream/server acceptance is pending production
  network configuration.

## 2026-09-16: Vemory real-time meeting center

- Changed the meeting-center primary read path to the authenticated server-side
  Vemory list. Browser clients still use the existing protected PDCA endpoint;
  Vemory credentials are never exposed to the browser.
- Normalized live Vemory records into the page model, including source date,
  owner participation, duration, and stable external ID. Unprovided
  internal/external or meeting categories display as `unknown`, never as an
  invented internal meeting or routine report.
- Added a 07:00-22:59 Shanghai-time 30-minute Vemory snapshot job. Snapshot
  upserts are keyed by a database-enforced Vemory external ID; a failed or
  incomplete source read preserves the previous database snapshot. A complete
  sync removes only cancelled Vemory snapshots, never legacy records.
- Made the page state explicit: live Vemory data, labeled stale snapshot, or a
  visible unavailable error. Removed the old bridge from the primary list path.
- Corrected meeting task dispatch payload translation so page `owner` and
  `title` fields become the legacy writer's assignee and task text.
- A missing source and missing snapshot now returns HTTP 503 from both the
  list and summary APIs; neither can publish a fictitious all-zero meeting
  summary. Stale notices display their latest snapshot time.

Verification:

- Focused backend: `59 tests` passed in `12.740s` for Vemory list, pagination
  completeness, atomic snapshots, cancellation cleanup, source-date,
  stale-fallback, scheduler registration, and async request boundaries.
- Full backend discovery after rebase to the latest `main`: `438 tests` passed
  in `60.809s` with
  `python -m unittest discover -s tests -p 'test_*.py' -q -b`.
- Frontend: `8 tests` passed; Vue typecheck and production build passed.
- Docker Compose configuration passed with disposable non-secret validation
  values. Final Docker image `sha256:0eb6b00278850cdc3939a089ec9a9a832faf5fa339e539b0048227b6716a6b8f`
  passed in-container frontend tests, typecheck and production build; its
  fresh SQLite Alembic migration created the Vemory source column and unique
  external-ID protection. Isolated smoke returned `/health` 200 and
  `/app/meetings` 200. No production deployment was created.

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
- PR and main CI passed the production image, SQLite container, and disposable
  PostgreSQL concurrency/scope/outage smoke gates. Production cutover deployed
  exact SHA `d8404663b5b9e15853b38ebb7f71ca06b2593d4d` to both the internal workbench
  and five-kit portal after PostgreSQL backups. Public health, admin login, 71
  user rows, authoritative admin scope, and T-1 five-kit reporting (5/6 for
  2026-09-09) were verified after deployment.

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
