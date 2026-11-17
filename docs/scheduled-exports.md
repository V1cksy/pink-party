# Scheduled encrypted exports and freshness

Linux captures the installed synthetic session and application environment, encrypts completed captures, and offers only ciphertext to an opt-in Mac user agent. The Mac authenticates and validates each candidate before publication or retirement of a rolling copy. [Batch 10](scheduled-export-report.md) records the actual scheduled chain and failure exercises. [Batch 8](recovery-off-vm.md) remains the evidence for rebuilding a fresh VM.

## Boundaries and schedules

The original manually managed vault and recovery identity stay outside the new rolling area. Initialization refuses an existing directory, so automation cannot silently adopt the pinned vault as a pruning target. The source guest receives only the public recipient. The identity stays on the Mac, outside rolling storage, Git and the plist. Protected configuration contains its path, never the key value. Plaintext/key staging uses the separate private collection-state area; ciphertext transfer staging uses rolling storage. An interrupted job can leave private staging until the next locked attempt. SSD secure deletion is not claimed.

| Operation              | Normal schedule                                                     | Execution and storage bounds                                                                                                              |
| ---------------------- | ------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| Linux capture          | 30 seconds after timer activation, then 15 minutes after completion | Existing 30-second service, 64 KiB archive, seven snapshots; separate attempt record                                                      |
| Linux encrypted export | 45 seconds after timer activation, then 60 seconds after completion | Separate 90-second restricted unit, 15-second age subprocess, 128 KiB ciphertext, seven exports                                           |
| Mac collection         | launchd `StartInterval=60`, while the user is logged in and awake   | 90-second worker bound, 25-second guest request, 256 KiB response cap, 128 KiB ciphertext, seven rolling copies plus one publication slot |
| Freshness inspection   | Explicit command; each collection also checks source freshness      | Capture at most 1200 seconds old; export/collection attempts at most 180 seconds old; bounded reasons and 48 attempts per job             |

The combined systemd activation/inactive timers can fire earlier on reactivation when a previous inactive deadline is already due. Schedules do not promise a recovery point or availability. launchd does not wake the Mac, log in a user or start Lima. Missed intervals do not represent completed work. A 15-second Mac interval is available only to shorten a bounded failure exercise; it is not the default. See [Apple's user-agent guide](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html) and [systemd's timer reference](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html).

The backup unit retains `PrivateNetwork=true`, `AF_UNIX`, no capabilities and its existing filesystem restrictions. Its new wrapper writes attempts to a separate root-only status directory. The exporter has its own network-isolated sandbox, cannot read the live credential directory or restore store, and can write only its export/status directories and the existing backup lock. It reads completed archives while holding that same lock, so capture retention cannot remove the selected input. It validates the bounded snapshot set and skips encryption when the selected archive is unchanged. A busy lock fails promptly; the next timer invocation is the bounded retry. Deployment pauses the export oneshot even if its timer is inactive and resumes only a previously active export timer.

## Install, enable and inspect

First follow [Linux deployment](linux-deployment.md) and [key/recipient preparation](encrypted-recovery.md#prepare-private-storage). Preserve the installed session/configuration and completed snapshots outside retention before deployment, because normal deployment replaces the session from Git. Never overwrite batch 8's protected originals. The installer adds age and installs the export units **disabled by default**. With a public recipient already installed root-owned `0600` under a `0700` parent, inside the guest:

```sh
sudo systemctl enable --now pink-party-export.timer
sudo systemctl list-timers pink-party-backup.timer pink-party-export.timer --no-pager
sudo systemctl show pink-party-export.service -p Result -p ExecMainStatus
sudo journalctl --namespace=pink-party-backup -u pink-party-export.service -n 20 --no-pager
```

Detailed status contains private archive names and hashes. Redirect inspection output to protected evidence rather than sharing it:

```sh
sudo python3 -B /opt/pink-party/app/deploy/linux/scheduled-export.py inspect
```

On the Mac, use owner-only configuration outside the repository. This example deliberately creates separate new rolling/state directories and references an existing identity:

```sh
umask 077
mkdir -p "$HOME/.config/pink-party-automation"
chmod 0700 "$HOME/.config/pink-party-automation"
python3 - <<'PY'
import json
from pathlib import Path
home = Path.home()
config = home / '.config/pink-party-automation/collection.json'
value = dict(version=1, vm='pink-party',
    store=str(home / 'Library/Application Support/PinkPartyRecovery/rolling'),
    state=str(home / 'Library/Application Support/PinkPartyRecovery/collection-state'),
    identity=str(home / '.config/pink-party-recovery/recovery.agekey'))
with config.open('x') as stream:
    json.dump(value, stream)
config.chmod(0o600)
PY
CONFIG="$HOME/.config/pink-party-automation/collection.json"
python3 -B deploy/recovery/collector.py init "$CONFIG"
python3 -B deploy/recovery/launchagent.py install --config "$CONFIG"
python3 -B deploy/recovery/launchagent.py enable
python3 -B deploy/recovery/launchagent.py inspect
python3 -B deploy/recovery/collector.py inspect "$CONFIG"
```

The LaunchAgent runs in `gui/UID`, with no root daemon or login item. Installation copies only the public helpers and actual TypeScript validators into protected Application Support storage, avoiding reliance on background access to Desktop. Reinstall after helper changes, using disable/remove first. The plist references the configuration path, carries no key material, and routes stdout/stderr to `/dev/null`. Private state/history is the diagnostic record; generic CLI failures never print identities, configuration, hashes or real archive names. `inspect` emits only timestamps, health and a bounded reason. Its nonzero exit means unhealthy, including planned source downtime.

## What freshness means

Each job records `attemptedAt`, `finishedAt`, outcome, reason and its previous successful result separately. Export success retains `exportedAt`, capture time, archive digest and ciphertext digest. Collection success adds first collection time, last successful authentication/validation time and a bounded source-job observation. A repeated successful validation does not renew capture time or export time. File mtime and an age header are never health evidence.

Collection accepts a source observation only within 30 seconds of Mac time, then checks its backup/export job outcomes and capture age. Inspection permits the cached observation for the normal 180-second window, rather than treating it as a new clock measurement. Future timestamps, negative ages, rollback behind a recorded attempt/capture, missing state, stale captures, failed/running jobs, corrupt records, missing copies and changed ciphertext all fail closed. Inspection checks the retained file digest against its authenticated record. Collection authenticates and runs the exact archive, path/type/mode, manifest, integrity, session and environment validators again on every invocation, including an unchanged export. A healthy status establishes a recently authenticated, validated local recovery copy from a trusted source/store within these thresholds. It does not establish sender identity, independent provenance, immunity to valid replay, a healthy HTTP service or voice reception.

Failures retain the last successful result for diagnosis but make current health false. Corrupt status is kept and refuses silent reset. Save it privately, inspect the cause, then restore a known-good record or move it aside deliberately before waiting for a new scheduled result. Status/history publication uses fsync and atomic replacement. Each state directory has at most 48 history rows and one bounded private error record. Corrupt/missing status, a disabled scheduler, sleep or a powered-off host needs explicit inspection; there is no external watchdog or notification service.

## Publication, retention and interruptions

The request reads only the scheduled export offer, with a fixed guest command. It never streams plaintext or starts the VM. Transfer is bounded on disk, and subprocess stderr is suppressed. Each worker has a dedicated process group, cleaned on ordinary exit, timeout and interruption so timed-out Lima/SSH descendants cannot accumulate. Store/state locks reject overlap; systemd and launchd also serialize their own jobs.

A candidate must pass ciphertext digest comparison, complete age authentication, exact archive validation and capture/digest comparison with the scheduled export record before its ciphertext publishes atomically. Existing identical copies are revalidated without duplicate publication. At seven copies, a validated eighth may publish before one oldest eligible copy is retired. The immediately preceding successful copy and new candidate are protected. A full eight-copy area with no matching candidate refuses new publication. It does not prune to make space before authentication. The pinned manual vault never participates.

A pre-publication failure preserves completed copies. A retirement failure preserves the previous success record and reports failure; a newly authenticated copy may already exist in the spare slot. A later matching scheduled attempt authenticates again and can finish the retirement. An unlink followed by fsync/state-write failure may already have retired an old copy: no multi-file rollback or power-loss transaction is claimed. Interruption after ciphertext publication but before the success record may leave an unrecorded valid copy; it is not healthy until a later scheduled revalidation completes. Linux export publication/pruning has the existing analogous boundary. Inspect private evidence before manual retirement. Ordinary disk failures cannot guarantee continued state recording or durable filesystem writes.

## Repeat the exercise and restore separately

Close room clients and run disruptive exercises sequentially. With normal source data protected, inside Linux:

```sh
sudo python3 -B /opt/pink-party/app/deploy/linux/exercise-scheduled.py begin --work-name chain-run-01
```

Use a new `--work-name` for each run and the same name at finish. Initialization preflights collisions before touching locks/timers and saves a recovery journal before changing data. This serves a synthetic marker, observes a normal scheduled capture and protects it outside retention. Leave the schedulers running; observe a new Mac success whose **capture and collection times follow the start**, without invoking either oneshot manually. Use a new protected evidence directory for each run. The helper intentionally leaves the source in exercise state between begin and finish; after interruption inspect its private restore directory and verification lock before continuing.

Use the collected ciphertext with [the existing separate-directory restore command](encrypted-recovery.md#rebuild-a-fresh-guest). Compare restored bytes/modes against the authenticated payloads and private capture record. Do not use the working deployment as the restore destination. Batch 8 already tests fresh-VM rebuilding; this stage does not require another VM or transferring the private identity into Linux.

For the Mac-only failure runner, temporarily reinstall the agent with `--interval 15`, then:

```sh
python3 -B deploy/recovery/exercise-collection.py "$CONFIG" /ABSOLUTE/PRIVATE/EVIDENCE
```

It requires healthy collection, uses a disposable key/reference and separate full area, observes actual scheduled failure/recovery, stops a real transfer process group, rejects overlap and retains corrupt state for a scheduled attempt. It restores configuration in cleanup and never alters the working recovery identity. Preserve its private report. For source faults, inside Linux use a new workspace, then one case at a time:

```sh
sudo python3 -B /opt/pink-party/app/deploy/linux/exercise-export-failures.py initialize --work-name source-faults-01
sudo python3 -B /opt/pink-party/app/deploy/linux/exercise-export-failures.py missing --work-name source-faults-01
# Observe a new scheduled unhealthy Mac result before restoring.
sudo python3 -B /opt/pink-party/app/deploy/linux/exercise-export-failures.py restore --work-name source-faults-01
```

After a new scheduled healthy result, repeat individually with `stale`, `failed-export`, `corrupt` and `truncated`, always restoring before the next case. The helper protects source snapshots/status/ciphertext first. Every fault/restore command validates that complete checkpoint before touching timers or live captures; `check --work-name source-faults-01` repeats this preflight without mutation. Missing/stale cases alter only the disposable working capture set; failed export makes the public recipient temporarily unavailable while a real new scheduled capture is taken. Corruption cases alter ciphertext and coherent transport metadata so complete age authentication must reject it. Restore the protected working state even if an observation fails. Do not overlap this helper with deployment, application incidents or other recovery exercises.

Offline tests inject publication/retirement faults after authentication and compare prior good copies. The report distinguishes those faults from actual native-scheduler/process observations.

Finish the source exercise to restore original bytes/configuration and observe normal scheduled capture/HTTP monitoring:

```sh
sudo python3 -B /opt/pink-party/app/deploy/linux/exercise-scheduled.py finish --work-name chain-run-01
```

## Disable, remove and shut down

On the Mac:

```sh
python3 -B deploy/recovery/launchagent.py disable
python3 -B deploy/recovery/launchagent.py inspect
python3 -B deploy/recovery/launchagent.py remove
```

Disable unloads the user job; remove also deletes its plist and installed public runtime. Both leave protected configuration, ciphertext, state and identity intact. Removal retains the disabled launchd override. To reinstall later, install then enable explicitly. No stopped VM is started by any command above.

Inside Linux, disable export scheduling if it should not return at guest boot, then stop all project services/timers for maintenance:

```sh
sudo systemctl disable --now pink-party-export.timer
sudo systemctl stop pink-party-export.service pink-party-backup.timer pink-party-backup.service pink-party-monitor.timer pink-party-monitor.service pink-party.service
```

To remove only the optional units, remove `/etc/systemd/system/pink-party-export.service` and `.timer` after disabling/stopping, then run `sudo systemctl daemon-reload`. Keep stores/recipient and existing enabled application/backup/monitor units. From the Mac use the [guarded shutdown helper](../deploy/recovery/stop-vm.py), which requires a new current VZ stopped event before stale-host cleanup:

```sh
python3 -B deploy/recovery/stop-vm.py pink-party
```

To exercise source unavailability, stop the project units and use the guarded shutdown command while collection is enabled. Observe new scheduled `source-unavailable-or-transfer-failed` attempts and confirm `limactl list` still reports Stopped. Explicitly run `limactl start pink-party`, then wait for a new normal scheduled capture/export and authenticated collection. Finish with the disable/removal/shutdown steps above. The collector itself never starts the guest.

Keep the original disk, protected source files/backups, pinned export and separate recovery identity. Same-Mac encrypted storage protects against losing access to the guest or its disk image. Recovery after physical Mac loss requires independently available ciphertext and key custody. Batch 11 exercised its [SFTP stage](offsite-backup-report.md) with a local fixture.
