# Linux backup and recovery exercise

Later evidence: [batch 8](recovery-off-vm.md) extends these same-disk exercises with encrypted off-VM export and fresh local Linux recovery. This report retains the original batch-6 scope.
On 16 November 2026, Codex implemented and performed this stage at the owner's request in the local Ubuntu ARM64 VM. This is assisted portfolio evidence for backup scoping, systemd scheduling, integrity checks, restrictive permissions and file restoration. Independent owner practice and professional backup duties are not claimed.

## What was recovered

The application reads a synthetic session file at startup. Its private Linux environment supplies credentials; startup regenerates LiveKit YAML from that environment. There is no database or persistent voice recording. The [operations guide](linux-backups.md) explains the inspected lifecycle and exact two-file scope; source and binaries are rebuilt separately. The installer's `previous` directory remains deployment rollback material.

The backup timer created an archive containing synthetic session A and the existing Linux environment. Restoration into a new root-only directory reproduced the captured bytes, hashes, owner and modes. Both the actual session validator and configuration validator accepted the recovered files. Working credentials were compared privately and never replaced or rotated.

Codex then changed the session to B, restarted the app and verified B through `/api/session`. Removing the session prevented healthy startup and produced the expected missing-file journal diagnostic. Restoring A from the retained archive, applying only that session and restarting recovered owned web/control health and the expected API response. A known-good private copy of the original session/configuration and separate restored files were retained for cleanup and inspection. Normal source session and configuration were restored afterward.

## Actual observations

Times below are UTC on 16 November 2026; elapsed job/recovery measurements use the guest process monotonic clock. They describe this small local exercise, not a recovery-time or recovery-point guarantee. Full inspected fields are in [validation-backups.json](validation-backups.json).

| Observation                                                    | Result                                                      |
| -------------------------------------------------------------- | ----------------------------------------------------------- |
| Normal backup timer activated                                  | 18:33:12.352                                                |
| Scheduled capture                                              | 18:33:42.628; completion observed at 18:33:42.960           |
| Backup creation, validation and publication                    | 140 ms, from the actual job's successful journal record     |
| Restore to separate directory with byte/hash/mode verification | 73 ms                                                       |
| Synthetic data loss requested                                  | 18:33:44.310                                                |
| Recovery started                                               | 18:33:45.445                                                |
| Restored session A verified through the application            | 18:33:46.357; 913 ms from recovery start                    |
| Later normal scheduled monitoring sample                       | 18:43:45.322, `up / web-control-ready`, `media: not-tested` |

The later cleanup sample is evidence of scheduled normal health, not part of the 913 ms recovery measurement. Wall-clock gaps between report observations do not measure client outage. The recovery measurement includes a fresh archive restore, session application, service start, owned-health polling and served-data comparison. It excludes machine provisioning, dependency downloads, human diagnosis, off-host transfer and new-machine credential recovery.

## Failures and protection checks

- Temporarily giving the private source environment an incorrect mode caused the backup unit to fail with `Input permission mismatch` and `Result=exit-code`. Completed archive hashes were unchanged and the healthy application retained its process. The mode was returned to `0600` in cleanup.
- A missing backup produced `FileNotFoundError`; a deliberately changed archive produced `Archive checksum mismatch`. Neither published a restore destination. The source session, credentials, running process/health and prior archive hashes were unchanged.
- A concurrent create attempt was rejected by the non-blocking lock. Offline tests cover invalid/duplicate/traversal paths, links, special files, permissions, whole-archive and per-file corruption, failed publication validation, interrupted staging, source mutation, bounded retention and clock rollback.
- A separate deliberately failed deployment activation was rejected. The health monitor recorded a fresh scheduled down sample after installer failure, while both monitor and backup timers remained active. Redeployment restored normal health with unchanged credentials. This repeats the deployment-failure boundary in this batch; earlier batch-5 checks are separate evidence.

## Verification

Mac and Linux `npm run check` passed TypeScript, 17 TypeScript tests, eight Python backup tests, the production build and formatting. All 13 Linux browser cases passed in 39.4 seconds with synthetic microphones. Browser results cover local voice transport separately from the file-restoration API check; no new physical-listening or separate-home result is claimed. The existing bundle-size warning remains.

Installed units passed `systemd-analyze verify`. Inspection found seven valid completed backups, root-only stores, `0600` archives/checksums, the configured execution/memory/task limits and disabled networking for the backup job. The monitor cannot access backup/restore credential copies. Backup journald usage was 1 MiB at inspection, with configured size/age budgets rather than a guaranteed history duration.

Three independent review passes resolved retention under clock rollback, reuse of the actual session schema, independent timer cleanup and stricter failed-restore assertions. A final documentation correction added a readiness retry after `systemctl start`. Isolated mutations reintroduced the retention and schema defects; their regression tests failed as expected. Raw logs and artifacts remain private.

## Limits and final state

Snapshots are plaintext private files on the same guest disk. They protect this tested synthetic file-loss case and do **not** survive VM/disk loss, host storage failure or root compromise. No encrypted/off-VM copy, full-machine rebuild, credential rotation or disaster-recovery claim is made. Applying recovered private configuration to a fresh system remains untested. [Backup operations](linux-backups.md) provides repeatable commands and interruption recovery.

The guest remains a local Linux lab. Mac Tailscale settings and policy were unchanged. Separate-home voice still needs another device/friend, Safari interoperability remains unresolved, and cloud deployment remains later work. Independent owner practice is not required before continuing implementation.

Final verification and planned shutdown are recorded in [validation-backups.json](validation-backups.json). The application, monitoring and backup timer are configured for the next guest boot; no Mac login item was added.

Normal source/session health, a fresh scheduled normal backup and monitoring recovery were verified before shutdown. Codex then stopped the application, monitor/backup timers and both oneshots, and confirmed guest sockets were released. Application and both timers remain enabled for the next guest boot. Guest poweroff produced the current VZ stopped event at 19:02:34 UTC before forced stale-host cleanup. The stale stop client and shutdown helper also required clearing. Final VM status is `Stopped`, with no remaining Pink Party Lima process; normal Lima host-agent shutdown remains unreliable.
