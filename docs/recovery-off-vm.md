# Encrypted off-VM recovery report

Recorded 17 November 2026. Codex implemented and ran this assisted local portfolio stage at the owner's request. The exercise adds encrypted storage outside a source VM and applies recovered Linux credentials and synthetic session data to a newly created Ubuntu ARM64 VM. It is not independent owner practice, professional backup work, a cloud restore or a credential.

## Recovery boundary and implementation

The original Lima/VZ guest was retained. Its installed data, private environment and seven known-good snapshots were protected outside normal retention before redeployment. The application backup unit retained its network isolation and existing restrictions. A separate age export operation validates a completed snapshot, encrypts inside Linux, bounds size/time/concurrency and atomically publishes a root-only encrypted copy. Guest export retention keeps seven completed copies; the Mac vault accepts at most seven and requires manual retirement after verification.

The dedicated native X25519 recovery identity is retained in a protected Mac directory outside both the VM and encrypted vault. Only the public recipient entered the source guest. The vault is outside Lima storage. Both locations share the same physical Mac disk/host: this demonstrates recovery after losing access to the source guest/disk image, and does not establish survival of Mac loss, owner/root compromise or loss of the only recovery key. Independent off-device storage remains future work.

The fresh guest used the checksum-pinned Ubuntu image, two CPUs, 1536 MiB RAM and a separate 12 GiB sparse disk. No original disk was cloned, mounted or shared. Shared host folders and application port forwarding were disabled; administrative localhost SSH was retained. Only one VM ran at a time. Recovery used manifest-filtered public repository source, checksum-pinned Node.js/LiveKit installers, lockfile dependencies, the encrypted copy and a separately transferred temporary recovery-key copy. No Mac environment, AWS credentials, Tailscale state or private cloud configuration was transferred.

The fresh-only installer validates and stages the recovered local-mode files, puts the recovered session into the build, and installs the original Linux environment after successful build. It rejects an existing installation/state and serializes installation. It does not run setup or generate replacement credentials for recovery. Service account, root-owned code/configuration, permissions, restricted systemd service, independent monitoring and scheduled backups are rebuilt from source.

## Observed recovery

The source's normal timer captured the clearly labelled synthetic batch-8 marker at **08:07:02.065 UTC**. Observation from timer activation took 31.691 seconds. Export completed in 185 ms at the exercise boundary; its CLI measured 155 ms internally. The Mac collected only ciphertext, then successfully authenticated and validated it with the separately retained key.

Source cleanup restored the original session and unchanged environment, verified owned health, validated current/protected snapshots and observed fresh matching normal backup and monitoring samples. All source service/timer/oneshot units were stopped while the application and both timers remained enabled for future boot. A new VZ stopped event at **08:08:38 UTC** preceded stale Lima cleanup; stopped-state and unavailable guest-shell checks established that recovery did not use a running source VM.

On the fresh guest, authenticated restoration into a separate private directory took **737 ms**. Installation, build and owned service readiness then took **47.906 seconds**. These observations exclude VM creation, package/runtime bootstrap, diagnosis and browser installation; they are not an end-to-end recovery-time objective.

Private comparisons established exact restored bytes, owner and modes for both files, and that the running service process loaded the recovered environment. The application served the recovered marker, which differs from Git's default session. A fresh scheduled backup captured those recovered files at **08:13:52.134 UTC**; scheduled monitoring recorded up at **08:13:28.987 UTC**. The normal backup timer was restarted for this observation; its oneshot was not manually invoked. Observing both scheduled records took 31.437 seconds.

The recovered guest passed all **22** service permission/boundary checks, including dedicated non-root ownership, capability restrictions, protected code/configuration, exact loopback TCP/UDP sockets, both backend-crash recoveries, manual stop, foreign-listener rejection and useful invalid-configuration diagnostics without credential logging. Normal service was restored after these sequential exercises.

## Failure boundaries and review

Twelve live encrypted-recovery cases rejected missing/wrong/unavailable key references, corrupt/truncated ciphertext, authenticated invalid archive/schema/path, an existing restore destination, bad-permission export input and actual CLI process-group interruptions with a blocking age stand-in to make these tiny operations interruptible. Each protected the healthy application files and process, owned web/control health, retained input ciphertext and previous good encrypted export. A normal authentication/export succeeded after interruption. The working recovery identity was never deleted; unavailable-key testing used a temporary copy.

Offline tests use real age encryption and actual application validators. They also cover size/time bounds, seven-copy retention and clock rollback, symlinks/modes, concurrency, interrupted collection, and injected file-write/atomic-publication failures after successful authentication and validation. Failed writes published no recovered destination and preserved healthy restored files, source snapshots and prior exports. Those filesystem failures were injected tests, separate from the live interruption exercises.

age authentication detects alteration/incomplete ciphertext; internal checksums verify archive consistency. Neither proves sender identity, freshness or provenance. Anyone with the public recipient can encrypt a new valid archive. Recovery assumes a trusted chosen private copy, source revision and operator; it does not establish resistance to a compromised source, rollback or operator malware. [Operations](encrypted-recovery.md) documents key custody, atomic boundaries, interruption recovery and reproducible commands.

## Media and source checks

All **13 browser cases passed in 39.9 seconds** inside the recovered guest, using synthetic microphones and the recovered environment. Two-way decoded audio, four-client capacity, authoritative admission, mute/unmute, leave/rejoin, capture cleanup, signaling recovery and responsive controls were verified. At four clients, all 12 received remote streams had positive decoded samples and audio energy; the smallest observed stream contained 132,714 bytes and 516,960 decoded samples. HTTP health was not used as evidence of media reception. No physical listening, separate-home call or cloud media path was added by this stage.

An initial browser attempt passed 12 cases and failed one UI assertion that treated the session paragraph as a heading. The corrected test compares the actual session paragraph with the served data and retains the static page heading. The complete rerun passed with the recovered marker unchanged; failed-attempt evidence remains private.

Mac and isolated fresh-Linux source checks passed **22 TypeScript and 40 Python tests**, type checking and production builds. Linux formatting passed with that source transfer; final Mac formatting and delivery checks cover the later documentation edits. age was 1.3.2 on the Mac and Ubuntu's packaged 1.1.1 in Linux. The existing bundle-size warning remains. Three independent review passes resolved vault retention, protected staging, collection interruption and verification gaps; the final review found no substantive blocker. The final test-selector correction was inspected against the HTML and exercised by the full browser rerun.

The final guest inspection validated all scheduled backups, confirmed no shared host filesystem, and found no configured credentials or recovery-identity value in 136 inspected public/build files or application/backup/monitor journals. Exact private comparisons, raw logs, reports and failed attempts remain outside Git. Public validation is in [validation-recovery.json](validation-recovery.json).

## Final state and remaining work

After media and disruptive checks, the recovered marker, original Linux credentials, owned health and fresh scheduled backup/monitoring were verified again. Selected private evidence was copied to the Mac. The application, both timers and both oneshots were stopped and sockets released. Recovery VZ produced a new stopped event at **08:57:12 UTC** before stale Lima cleanup. The task-created recovery instance and disk were then deleted; no project Lima process remained.

The original VM remains stopped, with its normal data/configuration, protected predeployment snapshots and private stores retained. Normal seven-copy snapshot retention had resumed during the source exercise; protected copies remain outside it. Source application/timers are enabled for a later guest boot, but are not running. The source VM directory and disk permissions were restricted to `0700`/`0600` on the Mac. The known-good Mac ciphertext was authenticated and validated again after cleanup; its separate recovery identity remains available privately with restrictive permissions. No plaintext recovered environment or identity was added to Git.

Mac project ports are free. Tailscale remains connected and Serve empty, with no settings/grant changes in this stage. A read-only AWS query confirmed the earlier lab remained removed and the account FREE/ACTIVE. No cloud resource, paid purchase or paid upgrade was introduced; historical usage from batch 7 may still post later and is not a finalized invoice here.

The delivered scope is local application recovery from an encrypted off-VM copy while the source guest is unavailable. Off-device storage, survival of physical Mac loss, full-system restoration and cloud restoration remain untested. Independent owner practice can be recorded when performed; it is not a prerequisite for continuing portfolio implementation.
