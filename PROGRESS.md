# Progress

## 2026-10-21: Task-only roles for three department members

- The user's final correction supersedes the earlier pause: 冯磊 joins department three; 刘春梅 and 付汪阳 join department five. All thirteen members contribute department sales and receive todo/closure follow-up. These three are marked task-only; MTO, formal report and sales process checks remain on the original ten members. Department three retains eight MTO proposals/day and department five four. Other targets, channels, schedules, rules and enabled state remain protected; fifteen C-to-B cards remain paused.
- Add verified IM identities for 冯磊 (12545) and 付汪阳 (13365), reusing the existing groups. Collect their messages and todos, skip specialty OCR/MCP for all three, and match 冯磊-1 exactly for sales. Missing or invalid amounts stay pending. Short reports, historical long output, cached messages, AI role facts/cache and missing-report conditions honor the role. The UI and structure preview label the three as “仅追待办”; roster synchronization expands only the two affected cards.
- Test-first: seven new role regressions initially failed (six failures, one missing-identity error). Focused discovery then passed 268 tests in 21.239 seconds, including source skipping, exact sales alias, role-aware cache, all output stages and stale long-copy coverage. A final 155-case focused run passed in 2.543 seconds after adding task-only long-format details. Frontend 35/35, typecheck, production build, Python compilation, both Compose configurations and diff checks passed. Isolated headless Chromium verified both roles, switching departments and saving the full roster with no page errors. Two-axis review found additional legacy carry-over, missing-owner placeholders, sales-specialty output, management-report scope and personal-target alert gaps. Those paths now honor task-only roles; four new review regressions were added. Further review added normalization for legacy routine MTO quotas/report-submission tasks and generated report/MTO evidence, while preserving specific business tasks and payment proof. New task-only message prefixes are covered by the bot self-message guard. Parser-origin outreach, MTO submission-quota and combined MTO/report reminders are also normalized; their three real parser cases first failed before the fix. The two concrete customer-delivery cases “提交MTO报价给徐豪” and “完成MTO报价给客户A” also first reproduced over-filtering; the quota matcher was narrowed to retain them. Final review-fix validation passed 259 tests in 2.953 seconds, including legacy Paris output, source skipping, business-evidence retention and own-message cases. Complete CI, exact-commit re-review and production verification remain release gates. No manual group messages were sent.

## 2026-10-20: One 督战官 report per department

- Compact production messages now use the confirmed ten-member cohort: 一部 于冰; 二部 杨晶晶、何海文、王宇彤; 三部 Lina、Safae; 四部 尤文静、Sana、张月馨; 五部 邓琳莹. Existing identity aliases and historical individual plans remain available. Each department receives one message per slot; tasks retain their responsible member.
- Department goals come from the confirmed department breakdown, not summed personal targets. Missing member values keep the combined total pending. Morning combines daily/weekly tasks and the existing four-MTO-per-person requirement; midday is brief; evening checks combined sales, closure, MTO qualification, reports and evidence. Conditions and AI facts use the same cohort, and AI cache keys include that cohort.
- Old per-person snapshot copy is re-rendered from its ledger before sending. A preview/apply configuration command validates and atomically updates the five existing card names and member lists, preserving channels, slots, timezone, rules and enabled state. Code import deduplicates by channel.
- Review fixes keep overflow and missing member/activity/closure data pending, preserve the WhatsApp synchronized-lower-bound label, distinguish captured MTO records from verified qualifying proposals, and mark unread or inconsistent MTO evidence for verification. Group-history collection now preserves unavailable responses, records per-person completeness, and skips OCR on incomplete history; failures and historical snapshots without provenance cannot become zero submissions or zero open tasks. The configuration page shows a read-only department roster from the same source; partial personal selections cannot enable or replace a running department card. Structure previews show the effective full cohort.
- Test-first: department tests initially failed on the missing module; card migration failed on the missing command; review regressions reproduced each issue before correction. The final focused run passed 300 tests in 29.100 seconds, including 25 new department/configuration regressions. Before the last history-provenance correction, full backend discovery passed 1,340 tests in 254.920 seconds (11 skipped); complete CI against the final commit remains a merge gate. Frontend 35/35, typecheck, production build, Python compilation, both Compose configurations and diff checks passed. Isolated headless Chromium verified the visible full roster, hidden personal editor and automatic roster synchronization when changing the target group, with no page errors. Fixed-commit review and live deployment/configuration verification also remain release gates. No manual group messages were sent.

## 2026-10-20: Short morning and midday 督战官 check-ins

- With `PDCA_DUZHAN_COMPACT=1`, morning messages retain monthly goals, today's tasks, this week's tasks and the existing four-proposal MTO requirement. Meeting tasks are matched to the person, while general group tasks remain visible. Midday messages keep the progress change, up to two open items and a reply request; weekly plans and activity/hour tables no longer repeat there. Evening messages add task closure, MTO, report, blocker and evidence checks plus the next action. The historical long format remains available with `0`.
- October's confirmed overseas target is 1600 万: 经销商二部 800 万、三部 400 万、四部 200 万、一部 200 万、五部破零. Department targets are stored separately from existing personal plans. The sales report validates the department sum; target maintenance preserves the department breakdown when a personal plan changes. Qualitative break-zero goals remain text.
- Twelve new regressions cover stage content, custom times, missing amounts, joint owners, empty ledgers, malformed targets, current goals and the robot self-message guard. The latest focused backend run passed 175 tests in 6.379 seconds. Frontend 35/35, typecheck, build, Python compilation, both Compose configurations and diff checks passed. The initial full backend rerun passed 1,312 tests (11 skipped); after review fixes, discovery ran 1,318 tests in 265.175 seconds with one browser resize timeout and 11 skipped. Browser inspection showed its animation timeline frozen at 0 after desktop-to-mobile resizing; starting the existing test at 320 px retained all four breakpoint assertions and passed both browser cases in 2.792 seconds. Exact-commit full CI and fixed-commit review remain release gates.
- Review fixes preserve jointly assigned daily tasks and group tasks without a business ledger, shorten missing-amount prompts, validate malformed target objects and remove stale campaign totals from the historical format. A read-only production snapshot from 2026-10-20 14:45 rendered the 于冰 preview as 228 characters in the morning, 97 at midday and 284 in the evening. The preview identifies its snapshot cutoff and was saved in the configured 督战官 delivery directory. Production currently uses the long format; release must switch its persistent setting to compact and verify all 15 C 转 B cards remain paused, with zero follow agents.

## 2026-10-15: Add return navigation and save scenario-card settings

- Omega record, assignment, and task detail views now expose a visible `返回场景卡` control. Returning from an accidentally opened record preserves the unsubmitted meeting topic and selected materials; `新练习` starts a fresh setup. Live voice disables navigation until the call ends.
- `保存本次设置` stores the selected scenario, edits, meeting topic, and extracted materials as an unconfirmed task draft. The task list can reopen it for review, confirmation, and later practice. Saving alone creates no session or report. Starting practice still persists the setup automatically.
- Test-first: the new backend draft regression failed with HTTP 422 before the `save_only` contract was added; the exact-image deployment test first failed on the missing `target_revision` argument. The combined Omega/deployment tests then passed 38/38. Final full backend discovery passed **1,218 tests in 365.487 seconds (11 skipped)**. Frontend tests passed **34/34**; typecheck, production build, Compose configuration with dummy non-secret values, and `git diff --check` passed.
- Headless Chromium exercised the real Vue UI with isolated demo APIs: desktop record → return retained the typed topic and uploaded file; save showed confirmation. At 360 px, return/save controls were visible, saved topic appeared in task detail, document width equaled viewport width, and the browser console had no errors. This browser check does not establish production deployment or physical-phone behavior.
- The independent Omega deployer can now select a tested exact main commit image, validate its revision, and keep the older main/worker containers running. Its existing active-call check, health smoke, and rollback still apply. Read-only production checks before release found main `fa5c9fa`, Omega web `1154bffd`, both healthy, and zero active realtime calls. PR review, merged-main CI image, and live verification remain release gates.

## 2026-10-14: Allow custom 督战官 send times

- 督战官 cards now accept one custom 24-hour `HH:MM` send time for each business stage: early, midday and late. The editor adds, sorts and removes time chips, reports invalid, duplicate and same-stage conflicts beside the field, and previews the same exact slots. Existing `10:00`, `15:00` and `20:00` configurations remain compatible.
- The editor now states the default workflow directly: collect business data and group feedback, identify work items, mark closed and pending items, then ask the owner to supply the next action and deadline. Optional condition cards only filter when a reminder is sent; optional action cards only change the focus line inside the otherwise complete check reminder. The group picker only lists channels already wired to the collection pipeline; an unknown channel can remain a draft but cannot be enabled. Disabled and code-imported cards preview themselves in the same configured context.
- Scheduler collection, send, backup, health, idempotency, snapshot and AI-cache paths now preserve minutes. Collection and backup jobs crossing midnight resolve the intended business date instead of recording against the scheduler date. Duzhan and CToB copy names the actual configured previous slot, sparse schedules describe current state instead of inventing a comparison, and late previous-day health recovery remains observable after a midnight restart.
- Later status messages now replace earlier states for the same normalized work item, including changed deadline/evidence wording and English completion terms. Short numbered replies such as `1. 客户A尾款已付款` are retained. Chinese `是否/了吗`, English auxiliary questions, question-mark completion phrases, and `confirm/check/verify whether/if ...` requests, including forms with a colon, comma, semicolon or dash, stay pending. A later explicit answer in the same message, including `现已到账`, `Paid:`, `Done:`, `Invoice paid.`, bare `Yes/是的`, polite forms such as `Yes, thanks/是的，谢谢`, a negative answer or a partial percentage, supplies the resulting closed, stalled or partial state without retaining the question wording in the item identity. A bare answer is interpreted against the question: confirming partial payment stays partial, confirming an unpaid state stays stalled, denying an unpaid state closes it, and denying that a partial payment is absent remains partial. `Confirmed: no payment received` remains stalled, `Confirmed pending` remains pending, and short positive receipt confirmations such as `Confirmed: funds received` close the item. A completed statement followed after a comma, period, colon or semicolon by an unrelated `anything else?` question remains one completed item. English and Chinese negatives such as `unpaid`, `未付款`, `未完成` and `未到账`, modal failures such as `could not have been completed`, future or uncertain work such as `will be completed` and `may possibly have been paid`, unconfirmed claims such as `尚未确认已付款` and `no evidence that ... has paid`, stalled work such as `no progress`, negated completion such as `not 100% completed`, and partial work in prefix or suffix form such as `50% has now been paid` and `now paid only 50%` remain open and still merge with a later explicit completion update. English and Chinese future partial wording such as `will be partially paid`, `计划完成50%` and `预计部分付款` remains planned. Current states are matched by business stage: a later payment can resolve an earlier unpaid state, and a later full or partial receipt can resolve an earlier unpaid or unreceived state, while `已付款，但尚未到账` and a future receipt requirement remain open. An explicit current state wins over a compatible earlier historical plan, partial state, negative or unconfirmed claim even when the sentence mentions history afterward; overlapping negative wording never becomes completion. Factual past completion with `on time`, a date or a clock time is closed, while an actual future deadline remains planned. Temporal words and relative deadline quantities are removed from normalized task identity so historical and current versions merge. Imperative `Complete ...` tasks and `Paid media` labels do not close an item; explicit `Done:`/`Paid:` markers, emphatic positives such as `not only paid`, simple past statements such as `Customer A paid invoice`, and `paid` with a time or amount do. Exact identity retains complete order IDs, including status-like words inside an ID, protected English customer names such as Will, May and Paid, Chinese names or business phrases containing `后`, and canonical currency/amount evidence so separate orders cannot collapse while equivalent forms such as `USD 10,000`, `10,000 USD`, `$10,000`, `RMB 10万` and `10万 RMB` still match. A `W` suffix only means ten-thousand when it is a standalone suffix, so an English word after an amount cannot inflate the evidence. A new evidence-bearing update falls back to an evidence-free base only when both sides are unique and their evidence does not conflict. The 12-item cap keeps the most recently added or updated items. Business data ownership is bound to `channel_id`, so an edited display label cannot route one group's data to another group. Sparse long-format schedules describe the current state without claiming that all current replies or totals are new.
- Reply normalization strips polite tails without deleting an answer's business object, so `Invoice paid` and `Order paid` stay distinct. Explicit receipt replies may include a repeated customer name, `yesterday`, or an amount and still close the matching item; `received tomorrow`, a negative receipt, and a partial receipt remain planned, stalled, and partial respectively. Complete `100%` suffixes, `Paid in full`, a direct `Complete`, and Chinese `付款了/支付了/到账了/完成了` close and merge the matching open item. Scope words such as `All/全部/都` do not split that identity. `Pending confirmation`, `Awaiting confirmation`, passive inability such as `could not be confirmed`, qualified forms such as `awaiting finance confirmation`, and receipt or payment states followed by `需要确认/仍需财务确认` remain open. English forms such as `hasn't been confirmed`, `isn't confirmed` and `couldn't be confirmed` also remain open. A later explicit receipt supersedes an earlier transition state such as `待确认` or `pending confirmation` across a clause boundary, while `仍待确认`, `still pending confirmation`, `尚未确认`, `unconfirmed`, `still needs confirmation` and contrastive `but/although` wording still block closure. `待财务确认后已到账` records the later transition as closed. `已无需确认`, `不再等待确认`, `does not need confirmation`, `needs no further confirmation`, `no longer needs confirmation`, `not awaiting confirmation` and `no longer unconfirmed` do not turn a confirmed completion back into a stalled item. The business noun `需求` is not treated as `需要确认`. Chinese refusal/negation, approximate or less-than 100% in prefix or suffix form, and completion followed by `this/next weekday`, `by the end of day` or `by EOD` remain open. `Paid media` and `paid-media` remain business labels at any percentage. Contextual matching treats Chinese `都` as a scope word for plausible simple or compound personal names, multiple people, collective subjects such as `所有人`, `双方`, `负责人` and `所有同事`, and plural business subjects such as orders, dealers and stores, while customer identities such as `成都`, `新华都` and `大成都` do not collapse into shorter names. A numbered item containing an internal colon is not parsed a second time as an unnumbered named-order item.
- Fixed-commit review caught twenty-four release blockers. Plain, non-numbered status replies, including short Chinese forms such as `客户A已付款` and English forms such as `Customer Alpha invoice paid`, now update an existing numbered item without turning unrelated chat into new work. `requires`, `is required`, `waiting for`, `confirmation is still required`, `confirmation remains required/pending`, `confirmation is still needed`, `confirmation is no longer required` and their other negated forms now follow the same confirmation semantics and identity as `needs confirmation`. Fronted negation such as `no bank confirmation remains pending/required` closes the item. Historical `confirmation was pending/required yesterday` and a past confirmation state before a later current receipt no longer change identity or override that receipt; `confirmation was not pending` is also removed from identity. A sentence that explicitly carries the past state into the present, such as `was pending but is still pending` or `was required and remains required`, stays stalled. The same holds when the continuation follows a period, comma, semicolon, newline or an intervening historical word; same-sentence or cross-sentence `was required/needed ... no longer required/needed` closes and merges into the original item. Cross-sentence `It is required/needed` is only a confirmation state when its antecedent explicitly names confirmation or verification, so completed payments that are `is still` or `remains required/needed` for audit or order release remain closed and share the original item identity. DB scheduling now honors the 督战官 and C 转 B switches independently, keeps `@督战官` polling enabled in DB mode, fixes C 转 B to `Asia/Shanghai` in validation, preview and runtime, and checks every enabled C 转 B slot through its own run and snapshot health evidence. DB C 转 B-only mode registers and executes that health scan when the ordinary 督战官 plane is disabled; code-source C 转 B-only mode does not start the DB-only scan or emit false 督战群 alerts.
- Test-first regressions covered validation, runtime registration, flow propagation, preview, exact previous-slot lookup, health matching, item status updates, channel/data binding, sparse schedules and midnight boundaries. End-to-end group-message cases verify that the saved status and displayed progress agree, repeated historical/current subjects merge back into the original item, lowercase Will/May names stay distinct, multiword customer names and subject-verb-object payment statements close correctly, a later full completion wins over an earlier partial state, and completions with a future weekday, ISO date, clock time or `to be fully paid` remain planned while their deadlines do not change task identity. The 督战官 suite passed **221 tests in 14.283 seconds**. Full backend discovery passed **1,278 tests in 269.848 seconds, with 11 skips**. Frontend passed **35/35** tests, typecheck and production build. Isolated Chromium desktop/mobile checks added `09:35`, rejected its duplicate, removed `15:00`, exposed the same preview options, stacked fields on narrow screens and reported no console error.
- Default and standalone walk-in Compose configurations passed `config --quiet`; `git diff --check` passed. A remote pre-build could not resolve Docker Hub base-image metadata because the production host refused the registry connection, so exact-commit CI image construction remains the required container build gate before deployment.

## 2026-10-13: Polish the public 督战官 editor after live asset verification

- The first release, commit `2404704696fc66d279bdb79d017006fcec83b389`, is healthy in both `pdca-workbench` and `pdca-omega-web`. Public `/app/admin/duzhan-agents` serves the new JS/CSS assets and the protected admin API returns HTTP 401 without a session. An isolated Chromium render of those public assets found a raw `has_data = 是` card subtitle and an oversized preview gap on tall viewports.
- Condition cards now use the server schema's Chinese option label and clear send timing. The editor and preview share one right-hand column so the preview follows the save controls regardless of sidebar height; unavailable reorder arrows are hidden.
- Test-first: the new condition-summary assertion failed on the raw key before implementation. Frontend tests passed 28/28, typecheck and production build passed. A headless Chromium render with 21 isolated mock groups showed the Chinese subtitle, a 14 px save-to-preview gap, and zero page errors; a 390 px mobile viewport had no horizontal overflow and displayed all four steps. No production configuration or group message was changed by these browser checks. Both Compose configurations passed `config --quiet`.
- Full backend discovery passed 1,182 tests in 337.906 seconds (11 skipped). Exact-commit CI, merge, dual-container deployment, and public asset verification remain release gates for this follow-up.

## 2026-10-13: Make the public 督战官 group editor understandable

- The user screenshot was the old three-column editor. Read-only production tracing found that Caddy routes `/app/*` to the independent `pdca-omega-web` container, still on the older image, while the main `pdca-workbench` container had the newer backend and SPA. A public HTTP 200 was therefore insufficient evidence that the new editor was visible.
- The editor now presents four ordered steps: target group, sending slots, optional conditions, and fixed/AI copy. Group search and status stay in one compact sidebar; JSON and imported legacy blocks remain available under advanced settings. Group UUID entry is behind a disclosure. New drafts contain the required group and time blocks. Saving, enabling, previewing and the scheduler restart requirement are stated at the point of use.
- Test-first: the new draft/position and group-renaming tests failed on missing exports before implementation. Frontend tests then passed 28/28, typecheck and production build passed. A headless Chromium check with isolated mock APIs rendered all four steps and saved a newly selected group and slot through the real Vue form. No live group message or production database write was made by that browser check.
- Full backend discovery passed 1,182 tests in 268.717 seconds (11 skipped). Both Compose configurations passed `config --quiet` with their existing untracked environment files. Exact-commit PR review, production image deployment, independent Omega web sync, and public asset verification remain release gates.

## 2026-10-13: Correct slot health across the code-to-database cutover

- Production revision `39d28cb8cd572a50c62b406859dc518d59eae651` is healthy with `PDCA_DUZHAN_CONFIG_SOURCE=db`; 19 enabled cards register 24 grouped jobs. The public admin page returns HTTP 200 and the protected runtime API returns HTTP 401 without a session. This deployment followed passing PR and main CI, including container/PostgreSQL smoke tests.
- A read-only production check found that today's 10:00 Shanghai slot has successful code-mode collect and push runs plus a snapshot, while the database-mode health view reports all three missing. The 15:00 slot has a successful code-mode push but a genuinely missing advance collection and snapshot. No production message was sent by this check.
- Test-first: two new tests failed against the deployed implementation, then `python -m unittest tests.test_agent_health -q` passed 14 tests. Health checks now use same-day code-mode evidence only when the corresponding database-mode run is absent; a database-mode failure is never hidden by an older code-mode success. Legacy snapshot group counts use the code roster.
- Production rollout of this health-display correction remains pending exact-commit CI and deployment. The first post-cutover database-mode slot is Paris 10:00 (16:00 Beijing); its 09:45 collection started and the send result has not yet been observed.

## 2026-10-12: Request native EndASR before draining an identified speech tail

- Physical-phone hangup reproduced the incomplete-tail error on production revision `55e83c3791c6a3974fedf83ef1265e4596000067`: job `0cd473ab-82fa-4828-82c2-0e4799c7bab0`, zero saved segments, microphone released, explicit hangup at 07:31:48 UTC and failed job at 07:31:56 UTC. Host playback was not verified as captured speech. This establishes the phone failure, not its exact provider cause.
- The common Doubao stop/resume boundary now sends the documented `input_audio_buffer.commit` (EndASR) once when an identified ASR input is already active. It still waits for that input's matching final, the old-session close acknowledgement, valid ownership and lease. No active identity is cleared by a commit acknowledgement; partial hypotheses are not promoted to final transcripts. Raw noise without an identified input does not trigger the new command. Late unfinalized inputs still fail safely.
- Test-first at the actual realtime-session, receiver and database-release seam: three new tests failed on the previous application (24.740 seconds), then all passed (11.736 seconds). They cover explicit stop, pause/resume and a commit acknowledgement without a final; the last remains a failed job. The resume fixture derives its epoch from the acknowledged state.
- A bounded real-provider test with the current application and isolated SQLite sent two seconds of fixed synthetic speech. Native ASR started at 0.839 seconds; commit acknowledgement arrived at 2.153 seconds while the input was still active; the matching final arrived at 2.603 seconds and closed it; session.closed arrived at 4.330 seconds. One sales final was saved and tail processing took 2.227 seconds. No production database, private speech or credentials were exported. This is provider protocol evidence, not physical-phone or human acceptance.
- Evidence: `D:/Vertu/data/excel/26年数据/10月/部门工作画像/督战官文件/Omega_实体手机复测_2026-10-12/尾稿根因修复/`. Full isolated regression, exact-commit CI, independent review, immutable deployment and physical-phone regression remain gates. Model routes and the frozen report candidate are unchanged.


## 2026-10-12: Isolate scheduled database backup from business synchronization

- Production health returned 503 because its newest successful database backup was older than 36 hours. Read-only Docker timestamps show that the daily synchronization job missed runs on both October 11 and October 12 (delays of 5:06:29.660581 and 1:02:41.067690). Its backup ran only after synchronization. The specific cause of the long scheduling delay has not been established.
- A standard server-local backup restored healthy status on the existing production revision `15af8972fe6175334a2ce3321660683fa91283a2`; no application release or database restore was performed.
- Schedule database backup independently at 02:00 on the existing scheduler timezone, with a dedicated one-worker executor, a 12-hour misfire window, coalescing, and one concurrent instance. Business synchronization no longer runs backup. Other jobs retain their existing executor and misfire policy. Backup format, existing atomic PostgreSQL file replacement, 14-file retention, startup backup, and health validation remain unchanged.
- A standalone backup exception or missing output marks backup health as failed and uses the existing failure alert. The new job does not call synchronization.
- Test-first: `python -X utf8 -m unittest tests.test_backup_scheduler` first ran 4 tests in 0.840 seconds and failed with 3 failures and 3 errors (missing independent job, backup still coupled to synchronization, standalone callable absent). After implementation, the new tests plus relevant scheduler registration/module regressions passed 115 tests in 0.216 seconds. Nine existing scheduler fakes in eight files now accept constructor keyword arguments; their assertions are preserved.
- An earlier broader local selection ran 125 tests with one failure in the unchanged health catch-up test. Full discovery then ran 1,139 tests in 304.874 seconds (16 skips) with one different failure: the knowledge frontend test required a built web bundle that was absent in this new worktree. No health catch-up failure occurred in full discovery. Both failed logs are retained; the narrower 115-test success does not override them. After building the web application, the complete knowledge frontend module passed 3/3. Frontend tests passed 26/26; typecheck, build and both Compose configurations also passed; exact-commit full CI remains required.
- Evidence, including original missed-run timestamps and local test logs: `D:/Vertu/data/excel/26年数据/10月/部门工作画像/督战官文件/Omega_实体手机复测_2026-10-12/备份调度修复/`. Credentials, logs and phone recordings remain outside Git. Full backend, frontend/Compose CI, independent code review, merge and deployment remain pending. The separate failed Omega report candidate is excluded from this change.

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


## 2026-10-12 Omega 挂断错误提示

- 实体手机用户确认“清楚 能打断”；主动挂断后麦克风释放，但服务端仍报语音尾稿未完成。真人语音整体验收尚未通过。
- 根因已确认的前端缺陷：`voiceClosing` 时忽略服务端 `error`，导致正常关闭对话框后看不到收尾失败。现在保留错误消息，仍等待既有关闭流程收尾。
- 测试先行：修改隔离移动端浏览器验收，在主动挂断时注入服务端尾稿错误。未修改 UI 时目标断言失败（没有 alert）；修改 UI 后同一完整移动端验收通过，麦克风与音频上下文释放断言保留。
- 本地前端 26 项测试、类型检查、构建、知识库前端 3 项测试及两份 Compose 校验通过。证据在交付目录“挂断错误提示修复”。完整 CI 仍为合并门禁。
- 未改实时语音收尾判定、输入归属或评分逻辑。固定合成音频的独立真实豆包测试收尾通过，但没有复现本次实体手机尾稿失败，不能据此宣称尾稿根因修复。
- 本分支基于已审备份树 `a03eed72e22780daeb153ad2583f48186840d614`；本地基线 `3d69c696` 与已合并 main `6a342b893891fb31e7e97c410ef27e73af92c80f` 同树。

## 2026-10-13 Omega 与 VPS Key 解耦

- 正式网站 `/app/omega` 已由 Caddy 转发到新 `pdca-omega-web` 容器 127.0.0.1:8771。它与主 PDCA 共享 PostgreSQL、用户和 Cookie 签名，关闭 VPS 启动检查与重复调度；`/omega-health` 与主 `/health` 分开。旧 `/omega/*` 演示页保留原路由，但不是正式陪练。
- 已运行的独立容器仍使用已发布生产镜像 `17c79bc703f57d1d9152c07473ee4baee4e55106`。Caddy 候选配置通过 `caddy validate`，原配置备份在服务器 `/etc/caddy/Caddyfile.before-omega-independent-20261013`；切流后公开 `/omega-health` 返回 200、VPS 与备份检查均标为不适用，主 `/health` 继续返回自身状态。
- 生产账号 `test` 经公网登录后，能读取原 24 个场景、21 次会话；同一 Cookie 能访问主 PDCA 有权 API。未登录的账号与 Omega API 均返回 401。公网新建会话的语音 WebSocket 收到 `ready`，发送 `stop` 后关闭并能结束；另一次文字回合生成对手回复，报告任务成功且返回九维结果。单轮 QA 的总分为 `null`，不能当作评分质量签收。
- 隔离容器放入无效 VPS Key 且不挂载原认证文件时，`vertu_health(force=True)` 为 false，独立 Omega `/health` 仍为 200。真实会议故障返回 503 的代码已通过红绿回归，但在新镜像发布前，线上旧镜像仍可能给出旧的 404 文案。
- 干净分支本地全量后端 **1,158 项通过，11 项跳过**；前端 **26 项通过**，类型检查和生产构建成功；Compose `omega` profile 和差异检查通过。首次全量后端在前端产物尚未生成时有 1 项失败；完成构建后该项及全量重跑通过。公司级公开验收仍受评分语义 P1、真人场景和实体手机签收门槛限制。
- PR #163 复核发现主站原为 hybrid 认证且配置了 VPS/Odoo 登录入口。补丁已改为保留 hybrid 登录展示与 SSO Cookie，同时将独立容器的本机 VPS 身份兜底关闭，防止匿名访客冒用服务器身份。两项新增回归先失败、实现后连同相关专项共 8 项通过；该补丁尚待最终 CI 和新镜像发布，当前在线独立容器仍是 local 模式。
# 2026-10-21: Editable monthly group sales and MTO rules

- Added an admin form for each department group and month: sales target in CNY wan (or first sale), daily MTO quantity per assessed member, and minimum quote amount in CNY wan. An independent group/month table retains history; version checks reject stale writes. Failed saves retain input. No card is automatically enabled.
- Collection, department sends, historical preview, AI facts/cache, MTO detail cache and evidence use the effective month policy. Existing OCR amounts are reclassified without another model call; missing sources remain pending. Three task-only members retain todo follow-up and sales inclusion while remaining exempt from MTO quotas. Existing paused C-to-B cards are untouched.
- Test-first evidence: new monthly test initially failed with `ModuleNotFoundError: app.duzhan_monthly_metrics`; implementation passed the new persistence/permission/qualification cases. Related 督战官 suite: **280 tests in 19.708 seconds, passed**. Full backend discovery: **1,365 tests in 306.132 seconds, passed with 11 skips**. Frontend **35 tests**, typecheck and production build passed. Isolated headless Chromium verified month history, quantity validation, combined save, conflict retention, task-only denominators and first-sale goals at 320/768/1024/1440 widths, with no page errors.
- Both default and walk-in Compose configurations passed using validation-only placeholders for required environment fields. `git diff --check` passed. Exact-commit PR/main CI and production verification remain release gates.
- Review identified inactive code-mode edits, loss of qualitative first-sale goals in the digest, stale derived quote descriptions and an OCR ceiling below a configured quota. Five failing regression cases reproduced these. Code mode now rejects monthly writes and disables the form; first-sale goals and derived descriptions are retained; OCR capacity covers the quota and truncated evidence stays pending. Post-review focused suite: **79 tests in 0.780 seconds, passed**; exact final-commit CI remains mandatory.
- 2026-10-22 follow-up: preserved all quote facts for quotas above 12 and aligned descriptions of legacy numeric quotes; two additional tests reproduced the failures before the fix. Final focused suite: **114 tests in 4.027 seconds, passed**. CI exposed one old OCR cap assertion that expected an incomplete result to be a complete count; it now checks `None` while retaining the two-image budget assertion. Monthly migration is revision **024**, following the new production revision 023, before integrating the latest main baseline.
