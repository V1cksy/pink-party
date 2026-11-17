# Batch 10: scheduled encrypted exports and freshness

Recorded 17 November 2026. I automated the path from a scheduled Linux snapshot to an authenticated encrypted copy outside the VM, with freshness checks independent of application HTTP health. The original pinned recovery material stays outside rolling retention. [Operations](scheduled-exports.md) contains setup, scheduling, failure exercises, separate restoration and cleanup commands; [validation data](validation-exports.json) records the inspected results.

## Actual scheduled chain

The source was the existing Ubuntu 24.04 ARM64 Lima/VZ guest: two CPUs, 1536 MiB RAM and a 12 GiB sparse disk. Before redeployment, I paused existing jobs and preserved the installed session/configuration and seven completed backups in a new protected directory. Batch 8's protected originals, export store, Mac vault and recovery identity were preserved. No second VM was created.

The application served synthetic data that differed from Git. A normal backup-timer capture was observed after 32.302 seconds. A second capture then went through the complete default scheduling chain, without manually invoking a backup/export/collection worker:

| Observation                                          | UTC             |
| ---------------------------------------------------- | --------------- |
| Normal scheduled capture                             | 15:30:56.798908 |
| Scheduled encrypted export completed                 | 15:31:58.046228 |
| New copy collected by the 60-second Mac user agent   | 15:32:30.474660 |
| Complete authentication and exact archive validation | 15:32:32.635561 |

The chain was observed 126.284 seconds after its start, including the wait for capture. Capture to completed validation was 95.837 seconds. These are observations on this lab, including scheduler phase and polling, not recovery-point guarantees.

A separate restoration from that automatically collected copy passed complete age authentication and the existing exact archive, path/type, integrity, schema and environment checks. Restored bytes, ownership and modes matched the authenticated payloads, and the archive matched the private source capture record. Restore plus an independent decrypted comparison took 1.192 seconds. Temporary restored plaintext was removed afterwards. The source never received the recovery identity. Batch 8 already establishes a fresh-VM rebuild; this stage reused that validator without repeating provisioning.

## Implementation and freshness evidence

The backup's network isolation and restrictions remain intact. Its wrapper now records attempts separately from successful captures. A separate restricted, network-isolated systemd export unit locks capture retention, validates completed snapshots and skips encryption for an unchanged archive. The opt-in Mac LaunchAgent uses protected configuration, bounded transfer and a dedicated worker process group. It never starts Lima.

The collector authenticates and validates before atomic ciphertext publication or rolling retirement. Seven completed rolling copies have one additional publication slot; the immediately preceding successful copy remains protected during retirement. The original manual vault/key are outside that mechanism. Decryption/key staging uses separate private state, with stale staging cleaned on the next locked attempt. Subprocesses, file sizes, history, concurrency and retention have explicit bounds.

Freshness distinguishes attempted/finished jobs, last successful export, first collection, latest successful authentication/validation and actual snapshot capture time. Revalidating an unchanged copy does not renew its capture/export time. Current health also requires acceptable source-job observations and a retained ciphertext matching its authenticated record. Missing/stale/corrupt state, running/failed jobs, changed files, future timestamps and rollback fail closed. The configured capture threshold is 1200 seconds; export/collection attempts use 180 seconds. No file mtime or age header alone establishes health.

A stopped application produced a scheduled HTTP-monitor down sample while the authenticated recovery copy remained fresh. With the entire VM stopped, two real scheduled collection attempts reported `source-unavailable-or-transfer-failed`; Lima remained Stopped until an explicit restart. The stopped-source observation took 59.783 seconds including guarded shutdown and both failed attempts. After the explicit restart, a new normal scheduled capture at 15:50:04.389073 UTC, export and authenticated collection were observed. Owned web/control health and a fresh normal scheduled HTTP-monitor sample were then verified separately.

## Failure exercises

The default 60-second Mac schedule proved the full chain. A temporary 15-second Mac exercise interval shortened later faults; the Linux units retained their normal definitions. Each disruptive case completed before the next began.

| Source fault                                                                        | Scheduled Mac unhealthy result observed after injection | Later scheduled recovery |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------- | ------------------------ |
| Missing working captures                                                            | 16.097 s                                                | Passed                   |
| Validated capture with a deliberately stale manifest time                           | 16.492 s                                                | Passed                   |
| Public recipient temporarily unavailable during a real new scheduled capture/export | 52.603 s                                                | Passed                   |
| Corrupt ciphertext with coherent transport metadata                                 | 15.858 s                                                | Passed                   |
| Truncated ciphertext with coherent transport metadata                               | 16.083 s                                                | Passed                   |

These are controlled input faults observed by actual systemd/launchd jobs. The corruption cases reached age authentication rather than stopping only at a transport hash. Protected checkpoints restored the working captures/status/ciphertext between cases; original application data/configuration and pinned material stayed intact.

Actual Mac scheduled attempts also rejected wrong, missing and unavailable **temporary** key references and a full separate capacity-fixture area, followed by scheduled success after each restoration. The working identity was never modified. A real transfer process group was stopped with zero response bytes written; an overlapping worker was rejected, interruption left the attempt visibly running/unhealthy, and the next scheduled run cleaned staging and authenticated successfully. Corrupt status was retained through an actual scheduled attempt, then deliberately restored before scheduled recovery.

Offline tests separately injected publication failures, interrupts before/after publication, retirement failure, clock rollback and skew, missing/mutated local copies and source timeouts. An interrupt after publication may leave a valid unrecorded copy; it remains unhealthy until revalidation finishes. A retirement or state/fsync failure can occur after a new copy publishes, or after an old unlink. This is not a multi-file transaction or a physical power-loss test. Prior success records/copies and the working deployment were checked at the appropriate failure boundary.

Three independent review passes found and resolved freshness-window, exporter-pause, staging-custody, descendant-cleanup and exercise-recovery hazards. Regression tests cover repeat-run collisions, saving the recovery journal before mutation and rejecting absent/corrupt checkpoints before touching timers or live captures.

## Checks and final resources

Mac and Linux `npm run check` passed 22 TypeScript and 59 Python tests, typecheck, build and formatting. The 17 new regression tests include real age authentication, separate restoration and a harmless process-descendant cleanup test. Shell syntax, Python parsing and workflow lint passed. The existing bundle-size warning remains. The unchanged [hosted workflow](continuous-verification.md) discovers the new tests on the standard public ARM64 runner; inspect its run against the delivered commit for hosted source/media results. No secrets or raw artifact uploads were added.

Original source bytes, root ownership/modes, loaded credentials, owned health and fresh normal scheduled capture/export/monitoring were checked before shutdown. The final export completed at 15:50:20.123014 UTC. All seven retained rolling copies and the original pinned batch-8 export authenticated and validated again after cleanup. Owner-file/key/ciphertext hashes and modes matched the private baseline. The source's inspected configuration/restore/export stores contained no native recovery identity.

The Mac agent is unloaded, with its plist and installed helper runtime removed; its disabled override and protected configuration/state remain. The optional Linux export timer is disabled. Application, monitor/backup/export timers and oneshots are inactive. Application, monitor and backup timers remain enabled for the next explicitly started guest boot. Final guarded VM shutdown completed normally, with a new VZ stopped event at 15:50:30 UTC; no force cleanup was needed for that final stop. The earlier unavailable-source stop needed stale Lima cleanup only after its own new stopped event.

The original VM/disk, normal data/configuration, both sets of seven protected backups, private stores, pinned encrypted export and separate recovery identity remain available. No project host agent or Mac project listener remains. Mac Tailscale stays connected, with Serve semantics and grants unchanged. No AWS command/resource, purchase, new physical device or paid runner was introduced in this stage. Hosted runs use the existing ephemeral standard public runner, within [GitHub's documented free public-repository boundary](https://docs.github.com/en/actions/reference/runners/github-hosted-runners#standard-github-hosted-runners-for-public-repositories).

This evidence establishes a recently authenticated, exactly validated off-VM application recovery copy while the source is available, plus visible failure/recovery when it is unavailable. Monitoring is intentionally stopped after cleanup. The vault and separate identity still share the physical Mac; off-device custody, physical-host disaster recovery, full-system recovery and power-loss durability remain outside this result. No new voice/physical-listening claim is made.
