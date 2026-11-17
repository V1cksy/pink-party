# Linux backups and restoration

Linux hosts keep small private snapshots of the synthetic session and generated host credentials. [The local recovery report](recovery-linux-backups.md) records batch 6; [the cloud report](cloud-report.md) records later AWS exercises. Both cover file recovery within one host, with no independent backup storage.

## Recovery scope

The application loads `data/session.json` at startup and serves that in-memory value through `/api/session`. Editing or restoring the file requires an application restart. There is no database, upload store, chat history or persistent voice recording. LiveKit room membership is transient.

| Input or state                                                                | Recovery treatment                                                                                                                                                                    |
| ----------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/opt/pink-party/app/data/session.json`                                       | Capture the installed synthetic session, including local changes that differ from Git. Restore as root-owned `0644`, beneath a private directory.                                     |
| `/etc/pink-party/pink-party.env`                                              | Capture the existing Linux local/private configuration and host credentials. Restore as root-owned `0600`, beneath a root-only directory. Never display it or automatically apply it. |
| Source, lockfile, service units, scripts and public assets                    | Recover from the reviewed Git revision and rebuild through the installer. The source-controlled session is also available in Git, but can differ from the installed file.             |
| Node.js and LiveKit binaries, dependencies and `dist`                         | Reinstall from pinned/checksum-verified inputs and rebuild. They are outside this backup.                                                                                             |
| `/var/lib/pink-party/livekit.yaml` via app `.local`                           | Regenerate at service startup from the environment; do not restore this duplicate secret.                                                                                             |
| Monitor history, private exercise reports, journals and deployment `previous` | Diagnostic/rollback material outside the backup scope. `previous` is replaced by deployment and is not a tested backup system.                                                        |
| Mac private files, Tailscale policy, identity and Serve settings              | Separate from this guest; excluded.                                                                                                                                                   |

A snapshot contains exactly three regular archive members: `data/session.json`, `private/pink-party.env` and `manifest.json`. The manifest records format version, capture time, byte counts, modes and per-file SHA-256 hashes. A separate `sha256` file checks the whole uncompressed tar. Inputs are limited to 16 KiB each and the archive to 64 KiB. Session and configuration validation reuse the actual application boundaries. The field set is restricted to four generated local-mode fields or six private-mode fields; duplicate fields, runtime overrides and local-code/private-mode mixtures are rejected. Private origin, interface address and invited identities remain inside the protected archive.

SHA-256 detects accidental changes. It does not authenticate an attacker-controlled archive and checksum. Treat the root-owned store as trusted private material. Backups contain plaintext credentials: do not commit, share, attach or move them to unprotected storage.

## Scheduling and failure handling

Deployment enables [pink-party-backup.timer](../deploy/linux/pink-party-backup.timer). It schedules a job 30 seconds after timer activation, then 15 minutes after each completed attempt, with one-second accuracy. This is an active-VM schedule without calendar catch-up while powered off. It gives no availability or recovery-point guarantee.

The independent [oneshot](../deploy/linux/pink-party-backup.service) runs as root, loads no credential environment, has a 30-second timeout, two-second stop timeout, 128 MiB memory cap and 16-task limit. Its filesystem is read-only except `/var/lib/pink-party-backups`; private temporary storage is isolated, networking is disabled, and application runtime state, monitoring history and restore directories are inaccessible. Each session-validation subprocess has a five-second timeout. The backup journal namespace uses the same configured 8 MiB budget, 1 MiB files and seven-day maximum retention as monitoring; active journal files can temporarily exceed the size budget.

[backup.py](../deploy/linux/backup.py) takes a non-blocking `flock` shared by backup and restore. systemd also serializes its oneshot. The store and snapshot directories must be operator-owned `0700`; archives, checksums and the lock are `0600`. A capture reads each exact regular file without following a final symlink, checks source permissions, validates contents, builds in a private staging directory, reopens and validates the archive, and rereads both sources to reject changes during capture. It syncs the completed files and directory before renaming the directory into its completed name, then syncs the store.

Keep configuration changes atomic and pause the backup timer during manual multi-file changes. This is a small-file capture, not a transaction across arbitrary concurrent writers. The installer stops the backup timer/oneshot before replacing code and resumes it on success or failure. The health monitor retains its separate failure-cleanup behavior and no dependency on backup or application health. Its sandbox also blocks the backup/restore directories so copied credentials remain inaccessible to it. The existing failed-activation regression now checks that both timers resume during application failure.

Retention keeps the newly published backup plus at most six prior copies. Wall-clock rollback cannot prune the just-created copy. Pruning happens only after successful validation and publication; capture failure leaves prior completed copies unchanged. An expired/killed job can leave a private `.pending-*` directory, cleaned on the next locked create. A failure after publication or during pruning can leave a valid new copy or extra old copies; inspect the failed unit before assuming retention completed. Root filesystem failure can prevent any job or journal write.

Inside Linux:

```sh
sudo systemctl list-timers pink-party-backup.timer --no-pager
sudo systemctl show pink-party-backup.service -p Result -p ExecMainStatus
sudo journalctl --namespace=pink-party-backup -u pink-party-backup.service -n 20 --no-pager
sudo ls -ld /var/lib/pink-party-backups
sudo ls -lt /var/lib/pink-party-backups
```

Successful journal records include a completed backup name and job duration, without payloads or credential hashes. Failures report a bounded reason such as a permission mismatch or checksum failure; inspect ownership/modes and unit status privately. `FileNotFoundError` means an expected input is missing. The oneshot is normally inactive between attempts. Monitor backup result and freshness separately from application health; this lab has no external backup alerts.

## Restore into a separate directory

Choose a completed name from the private listing and a new restore name. Inside Linux:

```sh
sudo timeout 30s python3 -B /opt/pink-party/app/deploy/linux/backup.py restore BACKUP_NAME restore-check
```

Replace `BACKUP_NAME` with the actual `backup-...` directory name. The command accepts names rather than arbitrary input/output paths. The destination is `/var/lib/pink-party-restores/restore-check`; existing destinations are rejected. Rerun with a new name when keeping an earlier restore for comparison.

Restore verifies the archive checksum, exact member set, types, paths, sizes, ownership metadata, permitted modes, manifest and payload hashes before writing any payload. It rejects absolute paths, traversal, links, special files, extra/duplicate members and unexpected permissions. It writes only fixed allowlisted paths without `extractall`, verifies restored bytes/owner/modes, and atomically publishes a new root-only directory. Missing/corrupt inputs publish no destination. A killed manual restore can leave a private `.restore-*` staging directory; inspect and remove it when no restore is running.

The command never changes the working deployment or credentials. To apply only session data on a **local-mode** host after inspecting the restore, close room clients and run sequentially inside Linux:

```sh
sudo systemctl stop pink-party-backup.timer pink-party-backup.service
sudo systemctl stop pink-party.service
sudo install -o root -g root -m 0644 /var/lib/pink-party-restores/restore-check/data/session.json /opt/pink-party/app/data/session.recovery-tmp
sudo mv /opt/pink-party/app/data/session.recovery-tmp /opt/pink-party/app/data/session.json
sudo systemctl reset-failed pink-party.service
sudo systemctl start pink-party.service
recovery_ready=false
for attempt in $(seq 1 30); do
  if sudo /opt/pink-party/node/bin/node /opt/pink-party/app/deploy/linux/service-health.ts; then
    recovery_ready=true
    break
  fi
  sleep 1
done
if [ "$recovery_ready" = true ]; then
  curl --fail --max-time 2 http://127.0.0.1:3000/api/session
else
  echo 'Recovery did not become ready; inspect the application journal.' >&2
fi
sudo systemctl start pink-party-backup.timer
```

The health monitor stays active during this operation. Check the served JSON against the chosen synthetic session and inspect a fresh scheduled health sample. Retain the previous session privately before replacement. On failure, use that known-good session, restart and diagnose the journal; do not overwrite credentials as a session-data fix. For the separate private-mode restore and outage checks, use [cloud operations](cloud-deployment.md#repeat-the-exercises); requests must retain private authentication.

Private configuration is restored for inspection and exact comparison only in the tested workflow. If an environment file is actually lost, stop the application and backup timer, preserve any surviving configuration privately, inspect the recovered file, and explicitly install it as `/etc/pink-party/pink-party.env` with root ownership and mode `0600` under the root-only `0700` directory. Avoid setup or first-install generation until the original credentials have been recovered. Reusing those credentials regenerates LiveKit YAML at startup. Applying recovered credentials to a fresh machine was not exercised here; a new-machine rebuild also needs the source revision, installer prerequisites and compatible binaries.

## Repeat the exercise

This command interrupts the local lab, changes the synthetic session and deliberately tests missing data. Run after deployment, with an empty room and both timers active:

```sh
sudo python3 -B /opt/pink-party/app/deploy/linux/exercise-backup.py
```

The [runner](../deploy/linux/exercise-backup.py) shares the service-exercise lock, retains the original session/configuration privately, serves session A, observes an actual normal-timer backup, restores and compares both files, rejects a bad-permission backup, rejects missing/corrupt restore inputs, rejects overlap, serves session B, removes the session, observes startup failure, then restores A from the archive and verifies owned health and `/api/session`. Cleanup reinstates the original session, preserves credentials, resumes both timers and waits for scheduled monitoring recovery.

Raw commands and reports remain root-only under `/var/lib/pink-party-restores/exercise-*`. If interrupted, inspect the lock, timer states, source session and that directory's `original-session.json`/`original.env` before recovery. Never remove a live run's lock. Do not blindly apply `original.env`; compare it privately with the working file. After resolving an interrupted run, remove only its stale verification lock, restore normal session/service and resume both timers. Retain the known-good archive and restore until review is complete; restore exercise directories have no automatic retention and should be removed privately when no longer needed.

Python 3 and its standard library are used for the archive/lock handling; no backup platform or database is added. `npm run check` now includes Python behavior tests alongside the TypeScript tests. macOS development also needs `python3` and Node.js 24.

## Storage limits

The archive store is on the **same guest disk** as the application and configuration. It survived controlled file loss and does **not** survive deletion/loss of that VM disk, host storage failure or root compromise. Archives contain plaintext private files. The AWS root disk used provider encryption, but no independent encrypted copy, full-system image, credential rotation or disaster-recovery test is claimed. Seven copies at the active schedule cover a short lab window; a stopped guest makes no new copies. The bounded cloud lab's disk and backups were deleted; the local VM and its stores remain retained. Independent storage remains later work.

References: [Python tar archive safety](https://docs.python.org/3/library/tarfile.html#extraction-filters), [systemd timers](https://www.freedesktop.org/software/systemd/man/latest/systemd.timer.html) and [systemd execution restrictions](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html). The installed units are verified against the guest's systemd 255.
