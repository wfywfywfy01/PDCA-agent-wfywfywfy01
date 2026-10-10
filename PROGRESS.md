# Progress

## 2026-10-10: Omega follow-up after production semantic acceptance

- Production rehearsal exposed another refusal pattern: after the seller offered an unapproved risk table, the buyer refused to forward it. The coach-v2 recommendation proposed another pending scenario table for selection and forwarding, and its outcome claimed minimum-goal success without counterpart confirmation. Independent semantic acceptance rejected this output despite passing functional checks.
- Advice now handles rejected questions and artifacts. If pending material is refused, the seller first checks the approvable boundaries, formal-document effect and alternatives internally. A request for internal investigation is executable; approval, a stamp or document delivery is never guaranteed. Scoring requires explicit confirmation of minimum-goal conditions and distinguishes partial progress, already answered information and compliance from order/approval progress. Public transcript input has explicit seq order.
- Prompt-only real-model replays still exposed factual mistakes: answered information omitted, earlier questions moved after a refusal, sales words assigned to the buyer and conditional forwarding treated as an agreement. All original failed candidates and independent reviews are retained. These failures led to an independent fact audit before practice generation and publication rather than accepting the prompt-only patch.
- Every report, including all-null reports, requires fact auditing using only public sequential speech and the validated report. The initial two-field global verdict is superseded by the exact per-claim checks contract described below. Five enumerated fact-error codes can reject it; the auditor cannot replace scores, facts or quotes. Invalid, truncated or negative audits regenerate once, then fail without report publication or memory preparation. External goals/rubric/boundaries need not be repeated in public speech, but claims of customer confirmation still require actual speech. Mentioned recipients do not prove approval authority. Cache and stored prompt provenance both advance to coach-v4.
- Owner activity, current source permissions, input hash, actual transcript digest, revision and lease are checked between calls and again before publication. A new regression reproduced publication after a transcript edit during practice generation; the final guard now blocks it. Focused audit tests passed 21/21 in 9.498 seconds. Existing fake adaptation first reproduced 8 failures and 1 error, then passed 83/83 in 56.834 seconds without dropping original assertions. These use explicit model test doubles, not evidence of real model semantics.
- Non-thinking audit candidates failed real semantic acceptance. The first captured-report evaluation rejected all 15 trials, including proposed positive controls; detailed review found both a genuine last-turn misstatement and an auditor over-inference from recipients to approvers. A clarified prompt then missed real errors, and none of three complete pipelines passed independent semantic review. Original gold expectations, reports and red results remain intact; two separately labeled curated synthetic controls received independent human review, including residual wording ambiguities and the exclusion of advice quality from the fact gate.
- The official DeepSeek API supports high thinking for deepseek-flash. Representative thinking probes correctly accepted a clean report and rejected a speaker/condition error. An 8192-token chronology probe exhausted its reasoning budget without final text and failed closed; a separate 16384-token retry correctly rejected chronology in 27.605 seconds. The intermediate candidate report/audit/practice budgets are 16384/16384/4096; high thinking and network timeouts 90/90/30 seconds are applied only to the official DeepSeek route; report jobs receive a 300-second lease, other jobs retain 180 seconds. No reasoning trace becomes report content. Thinking configuration regressions first failed 6/26, then all 26 passed in 6.902 seconds, including 250-second completion and exact 300-second expiry protection; the two existing practice expectations also reproduced the old settings, then passed in 0.823 seconds. API configuration reference: https://api-docs.deepseek.com/guides/thinking_mode/. Frozen 15-call fact checks and three bounded full pipelines remain gates before release, not promises of universal AI accuracy.

- Final integrated discovery initially ran 1,161 tests (11 skips) in 241.105 seconds with one obsolete flow-test expectation that report thinking was disabled; the PR CI reproduced the same mismatch. That expectation now checks kind-specific thinking, budgets and timeouts and its seven-test class passes. The final 15-call thinking audit returned valid JSON in all trials but matched only 12 original expectations: independent review classified one history statement as ambiguous and one compliance deduction as outside the fact-only audit; a third was a genuine answered-information omission that still passed. Original expectations and all outputs are retained. The coach and auditor now separate each answered qualitative concern from refused numerical data and preserve the scope of parallel negative claims. Two prompt contract regressions were red first, then all 28 focused audit tests passed in 7.909 seconds. Real-model regression and final integrated gates remain pending; these focused tests do not certify model semantics.

- The final parallel-claim prompt correctly failed closed on two bad reports but high thinking exhausted 16,384 tokens without final JSON, so that candidate failed availability acceptance. A bounded diagnostic compared audit low/16,384 and high/32,768 on the same original omission, clean positive and chronology reports: all six decisions were valid and correct. The smaller-budget low setting was selected only for the fact auditor; report and practice retain high, all token budgets/timeouts/leases stay unchanged. This does not establish general superiority of low thinking. Exact kind-specific configuration tests reproduced two failures before the one-line change, then all 35 focused tests passed in 8.522 seconds. Final actual-code fixed-case and bounded full-pipeline acceptance, final CI and production release are still pending. HTTPX timeout values cover transport phases, not a guaranteed total wall-clock duration; expired report leases still cannot publish. A temporary local connection outage interrupted the previous real-model collector; both public health and Docker recovered without network or server mutations, and the old collector subsequently exited normally. Its one successful trial out of three is retained as earlier-candidate evidence only.

- Actual-code low-thinking fixed replay accepted all six clean-positive trials and validly rejected six clear factual errors. A seventh bad report, which claimed the minimum goal was met while other reasons said it was only partly met and lacked counterpart confirmation, produced an extra type field and consistent=true. Strict validation blocked publication, but independent review still rejected the semantic result rather than crediting incidental format failure as a correct judgment. The fact prompt now explicitly allows only its two fields and checks contradictory statements about the same minimum-goal conditions; partial progress toward an ideal goal alone is not a reason to reject a genuinely achieved minimum goal. The contract test was red before this prompt-only change, then all 35 focused tests passed in 13.756 seconds. Jobs, budgets, leases, input scope and original gold remain unchanged. Final real-model replay and complete pipelines remain release gates.

- Three subsequent actual-code report/audit/practice pipelines completed the protocol; independent semantic review accepted two and rejected trial 3. Its relationship reason claimed the customer insisted on prior stamped guarantee terms three consecutive times, although seq 4 and 6 stated that condition and seq 8 asked which document form would be available after approval. The auditor accepted this overstatement. The original failure remains a release blocker; valid protocol alone does not establish factual accuracy. Report and audit prompts now require separate original-speech support for counts, continuity and force, and distinguish asking about document forms or options from insisting on one option. Both existing prompt contract tests were red first (2 tests, 10 failing subtests), then all 35 focused audit/flow tests passed in 7.046 seconds. This is contract and mock-guard evidence only; actual-model count/modality checks and complete pipelines still require semantic acceptance. No interface, error enum, goal input, model setting, token budget, timeout, lease or gold expectation changed. No commit or production change was made by the implementing reviewer. Logs and fixed-baseline diff: `二次复盘修复/support/count-modality-red-green/` under the evidence directory below.

- A six-call, same-prompt replay compared this exact count overstatement with a clean report and a separately labeled single-sentence corrected control. Low/16384 returned valid JSON in all three but accepted the bad original (41.297 seconds); its clean and corrected controls were accepted in 32.266 and 47.734 seconds. High/32768 validly rejected the unchanged bad original as unsupported_fact (53.609 seconds) and accepted the same clean and corrected controls (48.203 and 42.766 seconds). Original failures, reports and gold remain unchanged. This bounded configuration diagnostic is not formal actual-application acceptance or evidence of universal accuracy. The fact auditor now uses high thinking, 32768 tokens and a 150-second HTTPX timeout; report retains high/16384/90 seconds and practice high/4096/30 seconds. The 300-second report lease, strict validation, inter-call/publication guards, coach-v4 cache, interfaces and inputs are unchanged. Existing generation/flow regressions were red first (3 tests, 3 failures), then all 35 focused tests passed in 7.851 seconds; compilation and diff checks passed. Final 17-case actual-code fact checks, three complete semantic pipelines, full integrated gates and production acceptance remain required. HTTPX timeouts remain transport-phase limits, not a total wall-clock guarantee. Diagnostic outputs: `真实模型_audit_次数语气修复_最小3次.json` and `真实模型_audit_次数语气修复_high32768_诊断3次.json`; test logs and fixed-baseline diff: `二次复盘修复/support/audit-high32768-red-green/`.

- The selected high/32768 setting did not reliably reproduce its diagnostic rejection: a subsequent actual-code replay accepted the same bad original in 35.734 seconds, while the two positive controls were accepted in 19.468 and 61.016 seconds. All three responses were structurally valid. Final 17-case and three-pipeline semantic acceptance was not started, and the original false acceptance remains evidence of failure. No repeated same-configuration calls were used to select a favorable verdict.
- The global verdict is replaced by deterministic claim coverage: one original-text slot for outcome.reason, each of the nine indexed dimension reasons including null-scored dimensions, and every description in the three fact arrays. Text is not shortened, split or deduplicated. Missing/null reasons only form explicit null slots for unverified or unscored non-facts; scored reasons, achieved/partial/not-achieved outcome reasons and fact descriptions require nonempty strings. The auditor receives the complete public sequential transcript, the same validated report projection and all slots. Its only output is checks with exact claim_id/consistent/issues fields. Duplicate/unknown/missing IDs, bad shapes, non-booleans, inconsistent issue lists, truncated replies or the old global schema are invalid; any valid negative check blocks publication. All slots must be returned, including empty-text slots with no assertion. Scores, quotes, guard order, permissions, transcript hashing, 300-second lease, retry limit and model budgets remain unchanged. This enforces coverage, not guaranteed model accuracy.
- Test-first claim coverage evidence: the original implementation ran 36 audit tests with 16 failures and 109 errors, including subtests for the absent extractor/new validator signature; after implementation all 43 focused audit/generation tests passed in 8.172 seconds. Existing fake adaptation retained all business assertions: four representative tests first produced three failures and one error, then 83 related tests passed in 23.868 seconds and the complete isolated 390x844 UI acceptance passed in 13.593 seconds. The frozen integrated Omega discovery passed 203 tests in 128.300 seconds (10 PostgreSQL-dependent skips, 193 executed); compilation and diff checks passed, with core bytes unchanged across execution. These use explicit fake model decisions; real-model known-error/positive controls, complete semantic pipelines and final whole-project CI remain required. No additional repository paths, production changes or commits were introduced by the implementing reviewer. Evidence: `二次复盘修复/support/claim-audit-red-green/` and `二次复盘修复/support/claim-fakes-red-green/`.
- The first per-claim candidate's minimal five actual-model controls all matched their targeted expectations, but the subsequent fixed replay still accepted the original three-insistence overstatement. Three complete pipelines passed protocol and final-report fact review; only two passed advice review. Trial 1 again proposed an empty comparison framework and asked the client to supply criteria before completing internal investigation, despite the client's earlier refusal. The entire candidate remains unreleased; the favorable minimal replay does not override either failure. Original fixed cases, reports, scores, quotes and failed results are retained.
- The existing single audit now runs after practice generation, with unchanged model settings, budgets, 300-second lease and at most two total job attempts. The production sequence is report, permission/input/lease guard, practice when a scored blocker exists, guard, audit, guard, and the existing locked publication checks. An early local claim-shape check still rejects invalid scoring reasons before another model call. Keyword-only include_practice=False preserves pure-fact user payloads, the original 10+N slots and the five-code validation scope. Production explicitly enables a final original-text next_practice slot; advice must be a nonempty string when a blocker exists, while no-blocker reports retain an empty audited slot. The new refusal_precondition code is valid only for that advice slot. A negative or malformed audit publishes neither report nor memory and regenerates the complete pipeline once, without changing facts, scores or quotes.
- Both audit modes now explicitly prioritize conditional-question modality over loose paraphrase: a conditional choice between document forms cannot be counted as another current insistence, and each claimed repetition/strong demand needs its own supporting speech. The practice prompt requires actual internal findings before the client's reply and forbids client-filled criteria as a prerequisite; unknown values stay unconfirmed and approval/stamps remain unpromised. Test-first evidence for this extension: 50 audit tests reproduced 30 failures and 17 errors, including subtests for the missing keyword-only modes, in 15.962 seconds; all 57 focused audit/generation tests then passed in 22.280 seconds. Final Omega discovery passed 217 tests in 137.150 seconds (10 PostgreSQL-dependent skips, 207 executed), with core/test bytes unchanged during execution. Three existing practice call-order expectations first failed, then were updated to the new sequence without removing their business assertions; 83 related tests passed in 25.525 seconds and the complete isolated mobile UI acceptance passed in 16.250 seconds. Compilation and diff checks passed. These are overlapping deterministic/mocked boundary checks, not semantic acceptance. Default fact-only system text intentionally changes for the generic modality rule; its public transcript/report/claims user payload remains byte-for-byte unchanged. Evidence: `二次复盘修复/support/advice-audit-red-green/` and `二次复盘修复/support/practice-audit-fakes-red-green/`. Bounded real-model fact/advice controls, final integrated CI and production acceptance remain pending.

- The subsequent advice-audit candidate completed its fixed 17 checks with valid contracts in all 17 and correct decisions on all 15 clear factual controls, but only two of three complete pipelines passed. Trial 2 exhausted both existing attempts; its second audit correctly rejected a listening reason that attributed a sales question to the buyer and mixed earlier and later turns. The entire candidate remains unreleased. The two-attempt limit and factual rejection are retained; blind regeneration is replaced by private, bound retry clues rather than weakening the gate.
- Only a complete, strictly valid negative audit raises ReportAuditRejected, with the same public error text and the full server-manifest text and verified issue enums of every rejected old-candidate slot. The first rejection may persist an internal _report_audit_feedback payload bound to job ID, session ID, frozen input hash, revision and rejected attempt 1. Only attempt 2 may consume it after current source/owner/input/transcript/lease checks. Report and practice receive it as untrusted old-candidate data: both the candidate and auditor may be wrong, old indices do not refer to the new candidate, and the entire original transcript must be rechecked. The new audit receives no feedback. Invalid schemas, truncated replies and network exceptions never create partial or invented feedback. A rejection containing any null-text slot still rejects and retries once under the original contract, but stores no feedback at all; it never drops that slot to manufacture a partial clue list.
- Feedback persistence and retry status share one short game-then-job locked transaction with a fresh job row, the same live lease/token and current source, owner, actual transcript digest and frozen input checks. Invalid stored bindings or shapes fail locally before any external call. Success, final failure, expired second attempts and cancelled terminal jobs remove only the private key; malformed unrelated payload data is retained without a cleanup parse loop. The job API, published report and memory payload do not expose feedback. Default report/practice messages and both audit modes remain byte-for-byte unchanged without feedback; model settings, budgets, the 300-second report lease, retry allowlist and maximum two total attempts remain unchanged.
- Test-first retry-feedback evidence: the typed rejection component reproduced two errors before implementation and then passed both tests. Nine context/job tests reproduced 30 failing subtests and one error in 4.982 seconds; a separate transaction-lock regression failed before the same-transaction correction in 0.397 seconds. All 70 focused audit/generation tests then passed in 42.890 seconds, including full-text preservation, null fallback, strict binding/shape failures, privacy, audit-before-validation guard order, stale/expired leases and terminal cleanup. These are deterministic isolated model doubles, not real-model semantic acceptance. Final Omega discovery, related/UI regression, actual-model rejected-candidate recovery and three fresh complete semantic pipelines, integrated CI and production acceptance remain pending. Evidence: 二次复盘修复/support/retry-feedback-red-green/ under the evidence directory below.

- Earlier actual-provider acceptance completed four scripted synthetic speech rounds with native Doubao, pause/private coaching/resume (1.984 s), acknowledged stop, eight durable segments and an automatic 55-point report. Desktop/mobile report checks were 25/25 with 25 exact quote occurrences. A separate 390px test opened and closed a real corrected first-order ASR disclosure, 19/19. One earlier run was interrupted by an external Docker restart; another ended with an unclassified upstream error and incomplete-tail protection correctly blocked finish. Neither failed run is counted as passing or silently repaired.
- This follow-up changes no voice handshake, ASR normalization, frontend or data schema. Main advanced from c76f04e to 15af8972fe6175334a2ce3321660683fa91283a2 during work; all six current production business hotfix files match that latest committed main. Integration preserves those changes. Frontend 26/26, typecheck/build and original mobile acceptance (13.859 s) passed; final integrated backend, isolated mobile acceptance, real-model semantic review, PR/main CI and post-release checks remain gates.
- No-secret evidence, all negative candidates and final acceptance records: D:/Vertu/data/excel/26年数据/10月/部门工作画像/督战官文件/Omega_语音转写复盘修复_2026-10-10/二次复盘修复/. Eleven scoped paths cover progress, report/context/cache code, mandatory audit tests and existing model fakes; credentials and artifacts are excluded from Git.

## 2026-10-10: Omega raw ASR provenance and refusal-aware review

- Preserve the exact native sales ASR in `asr_original`. Correct only three observed phrases when this session's public title/brief/stage or earlier public words supply the matching term: `不急着订/定手单`, `市单周转量`, and `确项清单`. Legitimate trial/manual orders, amounts, dates, negation and counterparty speech remain unchanged. Private seller goals and memory never supply correction anchors. The native model's internal hearing is unchanged; this is bounded transcript normalization, not general ASR accuracy certification.
- Replayed native events compare the original text before normalization and reject a conflicting raw final. Corrected sales text feeds coaching and exact report quotes; the original remains available through the segment API and a folded, keyboard-accessible transcript control. Report focus/strength now use the same frozen weights and stable tie order as the backend.
- After the existing evidence-validated score, a small `practice` model call generates one action for the final blocker using the complete actual transcript. A refused question must lead to a new risk/value assessment action, rather than merely repeating the request. Only `next_practice` and `summary.next_step` are replaced. Strict JSON validation prevents replacing scores or facts; invalid advice retries once without publishing the old recommendation. Permissions, lease and input revision are rechecked before the second call and publication. Reports and cache provenance use `coach-v2`; no migration or voice handshake change.
- Test-first: transcription tests reproduced nine failures, then passed 14/14; the related voice/coaching/boundary suite passed 74/74. Focused advice initially reproduced three failures and one error; the initial five passed after implementation. Two actual database revocation/revision regressions then failed before the inter-call guard and passed afterward, for 7/7. Live segment raw-field regression failed before adding the field and passed afterward.
- Real server-local `deepseek-flash` replay used the previous fictional session's 12 actual segments and frozen 55-point report. Early candidates still repeated refused data requests and were rejected; after prompt revision three independent outputs passed independent semantic review. The 55-point score, facts, quotes and all other report content were unchanged. This is a narrow quality regression, not human calibration or broad model acceptance. Frontend 26/26, typecheck and build passed. Final full backend, CI/image and production acceptance remain release gates.
- No-secret logs, live replay outputs and independent reviews: `D:/Vertu/data/excel/26年数据/10月/部门工作画像/督战官文件/Omega_语音转写复盘修复_2026-10-10/`. Evidence and credentials are excluded from Git.
- Final local gate: backend discovery **1,125 tests, OK, 11 PostgreSQL-dependent skips**, 289.847 seconds; frontend **26/26**, typecheck/build, compilation, Compose and diff checks passed. An earlier harness incorrectly forced in-memory SQLite into unrelated pool tests (six setup errors); its output is retained and the final gate uses the normal test configuration. CI PostgreSQL/image and production acceptance remain pending.
- PR CI passed unit/frontend checks but caught an outdated mobile acceptance model fixture: it read report quote candidates for the new `practice` call. The same `KeyError` was reproduced locally, the fixture received a two-line JSON advice branch, and the complete isolated mobile API/browser acceptance passed in 14.929 seconds with all original control, memory and report assertions preserved. Production code is unchanged by this follow-up; full CI is rerun before merge.

## 2026-10-10: Omega acknowledged voice-stream boundary follow-up

- Post-deploy physical-phone testing of `a8cb53e3a22c4cb20c94aeacb61f09f2672268bd` passed its first pause/resume but failed its second resume with an incomplete-tail error. The public synthetic three-round test had passed. The physical result is retained as a failed acceptance, not overridden by synthetic evidence.
- A regression reproduced the raw-PCM problem: nonzero microphone samples with no native ASR identity made the old resume wait for a final that never existed. Resume now drains identified ASR while sending zeros, waits for the native old-session close acknowledgement, rechecks the owner and lease, and opens a new upstream session with the frozen role and recent public transcript before reopening the microphone. The old transport cannot attach late speech or replies to the new generation. Stop uses the same acknowledged boundary.
- A close acknowledgement is not a transcript final. An identified ASR input without a final, a missing close acknowledgement, revoked ownership, or a failed stream rotation still fails. Nonzero samples without an ASR identity do not become invented transcript evidence. Unrecognized short or quiet speech remains an ASR limitation; this change does not establish zero word loss. Public history excludes private coaching and seller limits.
- Cancellation during old-transport close now leaves the context available for outer cleanup. The cancellation regression first failed with one close attempt and an open transport; the fix passed with a second cleanup attempt and a closed transport.
- Reused native input, question and response IDs in a new connection could silently discard a new turn through the receiver's old caches. A regression reproduced that loss. Each native connection now has a distinct namespace; incoming identities use a fixed-length digest so old deduplication and output gates cannot match a fresh turn.
- Test-first evidence: the non-speech resume regression failed on the previous release. Candidate backend discovery passed **1,101 tests, 11 PostgreSQL-dependent skips**; after cancellation cleanup, **1,103 tests, 11 skips** passed in 183.173 seconds. After identity isolation, the final boundary/coaching/realtime suites passed **54/54** in 69.098 seconds, including nine boundary regressions. Frontend **23/23** tests, typecheck/build, Compose configuration and diff checks passed. Final full backend and CI gates remain required before merge.
- A real-provider application probe with disposable SQLite passed partial speech, immediate pause/resume, a second pause/resume after non-speech samples, two fresh replies, and acknowledged stop: **4 sales finals, 2 opponent finals, 6 durable segments, 1,334,224 output PCM bytes, 0 private PCM leaks, 0 uncompleted ASR identities**, succeeded job. This is synthetic speech evidence, not human microphone or listening acceptance. Final deployment and phone acceptance remain subsequent gates.
- The 78-second variant also passed with **6 durable segments and 1,391,798 output PCM bytes**. Synthetic public-voice prefixes of **0.4, 0.8 and 1.2 seconds** each produced a final before the old transport closed; their resume acknowledgements took **2.400, 2.539 and 2.802 seconds**. These three samples do not establish arbitrary short-speech accuracy.

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
