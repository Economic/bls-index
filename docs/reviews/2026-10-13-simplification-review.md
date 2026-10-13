# Codebase, design, and plan simplification review

Date: 2026-10-13. Review only; no production code or tests changed.

## Overall assessment

The ingestion implementation is substantially complete and well tested. The main risk to this project's simplicity is not the 33 source adapters: it is making an elaborate publication-management system a prerequisite for delivering a downloadable current series catalog.

The highest-value simplification is **publish only complete successful builds; otherwise keep serving the previous complete catalog and alert**. That would eliminate mixed daily publications and much of the per-program last-good, status, rollback, and cleanup state. This changes an explicit design decision and requires operator approval, not an implementation shortcut.

A second major simplification is to keep published scope fixed for v1, and defer dynamic scope release, sophisticated recovery/cleanup, and host-migration rehearsals until those operations are needed. Retain safe immutable uploads, conditional manifest replacement, honest source timestamps, and handling of uncertain writes.

The recorded full-33 benchmark is already feasible: 8,315,248 rows, 47,116,278-byte catalog, 268.58 seconds, approximately 4.62 GB Python peak RSS on a 16.77 GB runner (`docs/evidence/2026-10-13-phase1-benchmark.md:12-19`). No streaming framework, concurrent builder rewrite, or alternative database is justified by this evidence.

## Scope and verification

Reviewed all substantive production modules: HTTP/scope, native and synthesized builders, local Parquet bundles, combined validation, dry-build, CLI/probe/parse measurements/runner info, object storage, R2 staging check, clock, events, and notifier. Reviewed their dedicated tests, harnesses, representative fixtures, workflows, toolchain, dictionary, schema/source contracts, design, implementation plan, handoff, and benchmark evidence. Three local read-only research delegates covered ingestion, build tooling, and storage/harness areas; findings were synthesized and key references inspected by the parent.

Executed `./scripts/check.sh`: **538 passed, 1 opt-in live test deselected, 41.26 seconds**, exit code 0. No live BLS requests, R2 calls, workflow dispatches, or public writes were performed. Existing benchmark results are recorded evidence, not measurements rerun for this review. Python LSP navigation was unavailable because no supported language server was installed; targeted source inspection was used instead. The delegates could not write their individual reports because their contexts had no write tools; their returned findings are incorporated here.

This is a comprehensive architectural/simplification review, not a proof of all source domains, storage consistency semantics, or every fixture row.

## Prioritized design recommendations

### 1. Prefer complete-build publication over per-program fallback

**Priority: highest. Policy change; not yet implemented.**

Evidence: `design.md:16-21, 62, 95-105`; implementation plan `:42-56`. The handoff explicitly says publication/fallback phases remain unimplemented (`docs/phase1-handoff.md:25`).

The current plan serves an old complete catalog if aggregate assembly fails, but also allows a newly assembled mixture of fresh and last-good program files. This requires durable program files, separate last-good records, per-program source times, selection provenance, complete-verification times independent of artifact times, fallback validation, and special rollback rules to prevent displaced files becoming fallback.

**Simpler alternative:** build all 33; validate the complete candidate; publish only if all succeed. On any failure, leave the previous manifest/catalog untouched and alert through the workflow/monitor. Clients calculate source age from the successful catalog's timestamp. Operational attempt diagnostics stay in workflow reports, not in the discovery manifest.

**Retained:** full coverage, no automatic program removal, valid previous downloads, correct source age, independent failure alerts.

**Lost:** fresh updates to successful programs while another program fails. A persistent upstream problem stalls all updates. If that partial freshness is essential, keep fallback; otherwise it is a large availability feature without evidence yet demonstrating its necessity. Collect failure history before deciding.

### 2. Fix v1 scope in reviewed repository configuration

**Priority: high. Policy change; not yet implemented.**

Evidence: `design.md:14-15, 18, 63, 102`; implementation plan `:51-56, 77-78`.

The proposed release workflow introduces exact target approval, scope revisions, A→B→A stale-approval tests, multiple fingerprint reads, target-only versus current-scope failure status, contraction rules, and special fallback pinning. This is considerable machinery for rare changes to a 33-program catalog.

**Simpler alternative:** one reviewed supported-program list for v1, recorded in each successful manifest. Change it through a reviewed configuration/code release followed by a complete no-fallback build. Never derive scope from directory listings or a source failure. Use the same serialized publisher and conditional pointer update.

**Lost:** runtime operator-driven scope editing without a code/config release. If that capability is required later, introduce it then; future program implementations are already separately deferred.

### 3. Reduce the publication journal requirement, not the uncertain-write guarantee

**Priority: high. Architecture decision; not yet implemented.**

Evidence: `design.md:26-34`; implementation plan `:37-39, 71`. Every mutation currently requires prepared/submitting/terminal journal updates, full intended content, durable terminal markers forever, and recovery before even downloading.

A serialized writer still has lost-response and process-crash ambiguity. **Do not replace this with blind retries or assume an old read proves non-commit.** The adapter's committed/rejected/unknown model and disabled automatic conditional-write retries are justified (`object_store.py:3-15, 74-100, 125-174`).

**Simpler alternative to evaluate:** one durable unresolved-operation record containing intent, write ID, and expected prior version, with explicit manual recovery when outcome cannot be proved. Limit publisher operations initially to complete publication and deliberate same-scope recovery. Avoid an indefinitely growing general journal/index unless audit/replay requirements justify it.

This is not a drop-in protocol: crash windows, delayed/in-flight requests, clearing pending intent, and successor behavior still need a precise design and real-store tests. If safe recovery cannot be demonstrated, retain the current protocol or stop for operator intervention. Loss: automatic recovery breadth and permanent application-level operation history. Workflow logs are useful diagnostics, not a substitute for durable unresolved intent.

### 4. Defer cleanup automation and broad launch exercises

**Priority: high. Scope reduction.**

Evidence: `design.md:21, 72-75`; implementation plan `:53-54, 65-67, 79-80`.

Launch currently depends on dynamic releases, rollback/fallback repair, cleanup, public/private staging architecture, a second-host cutover rehearsal, and extensive delivery exercises. Validate the operations actually used at launch rather than requiring the entire future operations matrix first.

At launch, keep a documented manual recovery procedure and a small conservative retention policy. Without automated deletion, there is less risk of deleting live or unresolved references. Record object sizes and revisit storage costs; this is not permission for unlimited unmonitored retention. The benchmark estimates about 94.2 MB for a combined-plus-program set (`phase1-benchmark.md:23`); complete-only combined storage would be smaller.

Keep public HTTPS/checksum/cache verification, scoped credentials, serialization, real conditional-write checks, alert delivery, and overdue monitoring as launch requirements. Defer host relocation rehearsal until relocation is planned. A stable Pages discovery pointer is useful and cheap to retain; its full future client retry/cache policy belongs in separate client guidance, not publisher implementation gates (`design.md:77-89`).

## Concrete code simplifications

### 5. Establish one verified local snapshot boundary

**Priority: high. Some changes preserve the contract; wider changes require approval.**

`build_native_parquet` verifies and copies the downloaded input, then calls `parse_native_series`, which copies that private snapshot again and hashes it before/after parsing (`native_parquet.py:361-372`; `native_builders.py:719-754`). The writer rehashes the original records around output staging and reuse/publication (`native_parquet.py:228-300`). Synthesized builds perform adjacent full rechecks immediately before rename (`:287-293`).

Low-risk first step: retain the defensive standalone parser API, but use a shared internal parser for already-verified private snapshots. Remove the consecutive synthesized final checks in favor of one final check. Keep one-output-per-source-row and canonical output validation.

Broader simplification: define the privately owned verified bytes as the input to the build, rather than rejecting the resulting correct catalog because a separate original download path changed later. This retains provenance for the bytes actually parsed, but relaxes the current mutation-detection contract. Repeated original-path hashing cannot guarantee the source never changes between checks or afterward. Do not remove it silently.

### 6. Use run-owned local outputs instead of concurrent shared-cache publication

**Priority: medium/high. Narrower local API contract.**

The bundle writer uses Linux `renameat2` through `ctypes`, fails on other platforms, verifies destination collisions, and handles racing writers (`native_parquet.py:167-193, 268-301`). Bundle directory identity hashes provenance containing the current build timestamp (`:241-269`), so unchanged content at a different time generally has a different bundle identity. Meanwhile, dry-build already creates a unique run directory (README `:76-79`).

For the ordinary single-run builder, write beneath a private unique run directory and expose completion only after validation. Keep the remote artifact's identity as its Parquet SHA-256. This removes most local reuse/racing-writer branches and improves portability. Preserve current behavior if callers truly depend on shared concurrent bundle destinations; otherwise narrow the contract and replace tests of obsolete races with tests that failed builds do not expose completed outputs.

### 7. Remove duplicate synthesized decoding and tiny per-row dataframe allocations

**Priority: medium. Contract-preserving.**

- Snapshot parsers already enforce cardinality, but the InputSet wrapper decodes the `.series` again to count rows (`synthesized_builders.py:152-245, 282-361, 486-488`). Return/use the count already known rather than decode twice.
- Synthesized rows construct one-element Polars Series to validate each begin/end period (`:204-209, 332-337`). Use a shared scalar token validator or one vectorized column validation pass. The benchmark records SM build time of 17.81 seconds; these allocations are a plausible avoidable cost, not a measured isolated cause.
- The Parquet wrapper and parser both validate the InputSet metadata (`synthesized_parquet.py:86-99`; `synthesized_builders.py:395-438, 456-458`). Share one validated internal representation while retaining validation on public entry points.
- Native caller schema/nonempty checks repeat the shared writer's checks (`native_parquet.py:215-216, 368-371`). Consolidate these, not source cardinality checks.

### 8. Make example queries diagnostic, not acceptance conditions

**Priority: high. Small intentional behavior change.**

`dry_build.py:448-480` makes zero matches for unemployment or registered nurses a full-scope validation failure and deletes a dictionary-validated candidate. `tests/test_cli.py:191-225` fixes this behavior in tests.

Report counts/timings and optionally warn. Do not discard valid source-derived data because an English phrase changes. The design explicitly leaves search semantics/ranking to consuming clients (`design.md:57`). A malformed or omitted program should be rejected by source/schema/scope checks, not indirectly by two search phrases.

Keep the extra Parquet reload only when measuring downloaded-file load performance; use the existing combined frame for ordinary query diagnostics.

### 9. Separate measurement machinery from the ordinary build

**Priority: medium.**

`dry_build.py:186-290` always starts a background sampler that walks the run tree every 0.25 seconds. It reports sampled, not guaranteed peaks. Probe parse checks launch separate measurement processes (`parse_probe.py:1-5`; `probe.py:67-78`), and the manual workflow defaults parse measurement on (`.github/workflows/source-probe.yml:12-15, 40-48`).

Make transient disk sampling, detailed parse/RSS instrumentation, and search benchmarking an explicit measurement mode. Ordinary runs need stage durations, input/output bytes, final checksums, row counts, and useful failure reports. Preserve benchmark tooling for intentional architecture measurements rather than adding a new abstraction framework.

Keep a simple per-program progress checkpoint if interruption diagnostics are valuable. Consolidate report ownership: start/per-program/final writes plus the outer sampler rewrite currently spread it across multiple layers (`dry_build.py:76-98, 275-289, 331-421, 541-550`). No resumable build exists, so do not imply checkpoints implement recovery.

### 10. Assign validation ownership rather than weakening safeguards wholesale

**Priority: medium.**

Generic required/title/year/uniqueness checks appear in builders, combined validation, and `data-dict.yaml` (`combined_candidate.py:53-230`; dictionary `:13-60`). Some layering is appropriate: standalone parsers and untrusted future stored bundles are separate boundaries.

Suggested ownership:

- Source adapters: decoding, widths/headers, explicit program ownership, source field/ID relationships, lookup key cardinality and no parse/join loss.
- Combined boundary: exact requested scope, canonical types, global ID uniqueness, acceptance of reloaded bundles.
- Dictionary: public documented generic constraints and independent final artifact checks.

Use shared rules where duplication is necessary, especially period and synthesized-ID rules. Do not create a general plugin/validation framework. Static dictionary specification validation could run once per CI/job rather than per candidate; it currently takes only about 0.018 seconds in the benchmark, so this is conceptual cleanup, not a worthwhile performance project. Keep per-candidate data validation: its recorded 8.098 seconds is proportionate to the guarantee.

## Tests: keep guarantees, reduce implementation coupling

The 538 tests take about 41 seconds; test count alone is not evidence of overengineering. Broad parameterized adapter fixtures are justified by heterogeneous BLS formats.

Keep: real representative rows; strict UTF-8 and field widths; required IDs/titles; explicit program assignment; actual supported ID components; nullable metadata; duplicate titles allowed; duplicate/missing lookup keys; cardinality/no row loss; complete scope; global ID uniqueness; retries/truncation/changed inputs; pacing; checksum read-back; unknown conditional-write outcomes; real-store staging checks separately from Moto.

Simplify tests after simplifying their contract: adjacent mutation checkpoints, local competing bundle writers if outputs become run-owned, benchmark query gating, detailed instrumentation bookkeeping, and fault scenarios for release/fallback/cleanup operations deferred out of v1. Never delete a failing test merely to accept corrupted output.

The ordering harness is a useful self-test, but manually calling upload/verify/write helpers does not test an actual publisher state machine (`tests/test_harness_ordering.py:18-36`). Eventually prefer end-to-end assertions through the real orchestrator, with a smaller set of harness self-tests. Moto/fault-proxy success does not establish R2 consistency.

Exact ordered headers are defensible today. An additive/reordered-column-tolerant parser could reduce upstream brittleness, but needs a deliberate contract: map unique headers by name, require every consumed field, retain exact width checks, and reject ambiguous/shifted layouts. This is lower priority than eliminating duplicate passes and carries a risk of accepting upstream drift. Do not relax validated ID component or lookup relationships without evidence.

The double full source download costs about 3.32 GB versus 1.66 GB unique bytes in the benchmark (`phase1-benchmark.md:13`). Retain it under the present verified-input policy. It detects changes between reads, not an atomic BLS-wide snapshot or a consistently incomplete source. A future single-read policy or trustworthy-validator optimization is a consciously weaker/different guarantee, not a free simplification.

## Documentation and smaller correctness observations

1. **Conflicting current status:** README `:8` says Phase 0; schema `:80-82` says the full-33 benchmark remains pending; schema `:95` limits native Parquet to five programs. Handoff `:7-11` records all builders and successful full benchmark. Align these. Keep one current status note; do not duplicate evolving gate state throughout stable schema documentation.
2. **Repeated contractual prose:** scope, fallback, freshness, release, and recovery rules recur in deliverables, work sequence, done criteria, decisions, plan phases, and acceptance matrices. Replace repetitions with one normative rule/state table plus linked tests and a shorter implementation checklist. Keep research/evidence historical and clearly labeled.
3. **Probe diagnostic redaction differs from dry-build:** `probe.py:137-159` serializes base URL and failure detail directly, whereas dry-build validates/sanitizes them. Share safe URL/report rules or reject credential-bearing custom bases. Current production BLS URLs do not establish a leak; the risk is custom probe input recorded in artifacts.
4. **Gate 0 cleanup comment overstates concurrency protection:** `r2_gate0.py:147-156` checks the current body then deletes unconditionally. Another writer could replace it in that interval. The random 128-bit operator-only staging namespace makes ordinary overlap unlikely (`:50-65`). Document best-effort ownership checking rather than adding a locking subsystem for this one-off check.
5. **Events are snapshots, not immutable audit records:** JSON-copying caller input protects against caller mutation, but returned nested dict/list payloads remain mutable (`events.py:20-53`). Document trusted-reader convention unless immutable audit history is actually required.
6. **Notifier exception normalization:** the interface requires `NotificationError`, and `send_alert` catches that type (`notifier.py:1-5, 31-43`). Test normalization in the eventual provider adapter; no production adapter currently violates this contract.
7. **ID case equivalence needs an explicit policy:** parsers accept case-insensitive shape/component matches but duplicate detection uses source spelling (`native_builders.py:625-654`; synthesized `:167-174, 299-306`). No reviewed real-source evidence demonstrates case-only duplicate IDs. Decide/test the identity policy; do not label this a proven source defect.

## Recommended smaller launch path

Subject to approving the policy changes above:

1. Align current documentation and retain the existing successful sequential builders.
2. Remove redundant local parsing/hashing and separate optional measurements; preserve validated data boundaries.
3. Build the fixed 33 programs completely; publish nothing new on any failure.
4. Upload one content-addressed combined Parquet and verify bytes/checksum. Keep source provenance in the successful manifest/report; public per-program artifacts are unnecessary without fallback.
5. Conditionally switch a small `latest.json` containing schema version, run/write identity, immutable path, checksum/size, included programs/counts, and honest source verification/build timestamps. Retain enough previous information for deliberate manual recovery.
6. Precisely define durable unresolved-write handling and manual intervention; test lost responses/crashes against the real chosen store. Never blindly retry an ambiguous mutation.
7. Serialize the actual publisher; use scoped credentials, independent tested alerts and overdue monitoring; verify public HTTPS, checksum and cache behavior.
8. Publish the stable discovery pointer after the public manifest exists. Defer dynamic scope release, mixed catalogs, automated deletion, and host-migration exercises.

If mixed freshness and fully automatic cross-run recovery are nonnegotiable product requirements, the existing complex plan is more justified. In that case simplify duplicate code passes and documentation, but do not pretend the required state machine can be safely removed. The central decision is which availability and operational guarantees this small catalog actually needs before launch.
