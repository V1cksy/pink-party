# Off-device encrypted backups

The opt-in Mac uploader takes a completed [authenticated collection](scheduled-exports.md), authenticates it again, and sends only ciphertext to a dedicated SFTP directory. It verifies the staged upload and the published copy by downloading them and running the same age and application archive validators. The source backup and export units stay network-isolated.

## Access and custody

The batch-11 portfolio exercise ends with the local SFTP fixture. Use this procedure for a separate live exercise once the storage and custody below are available.

Use an already authorized storage host on a different physical device. Verify the account's quota, retention and access terms before enabling transfer. The target needs a dedicated directory, SFTP-only write access confined to that area, private regular files, and an atomic same-directory rename. Set a server-side quota with space for eight files of 128 KiB plus the small marker and filesystem overhead. Avoid provider versioning or hidden trash unless its separate capacity and retirement are understood and bounded.

Use one writer credential and one writer instance for the directory. The local lock serializes jobs that share the same state directory. Two machines or configurations pointing at the same SFTP directory are outside that lock. The storage administrator should enforce confinement via a chroot or provider equivalent. An initial working directory alone gives no confinement. Use a separate, independently retrievable SFTP credential scoped to reading the same files for recovery. Verify it can list and read the 0600 objects and cannot mutate them. On an OpenSSH host, a restricted read-only SFTP key can use the same confined storage UID and a forced read-only subsystem. Check the server's actual configuration. [OpenSSH SFTP manual](https://man.openbsd.org/sftp.1)

Keep the age recovery identity independently accessible from a separately approved custody location. Keep the independent recovery login and pinned SSH host key available without the source Mac. Never put the age identity alongside the remote ciphertext, in a launchd plist, in the source guest or in CI. Keep the pinned known-good ciphertext outside the rolling namespace and outside the write permission used for this directory.

Prepare 0700 directories for configuration, state and separately staged recovery. All private config and key files must use 0600. The writer JSON fields are:

```json
{
  "version": 1,
  "sshConfig": "/absolute/private/path/ssh.conf",
  "directory": "/dedicated/writer/directory",
  "collectionConfig": "/absolute/private/path/collection.json",
  "state": "/absolute/private/state-directory"
}
```

Use a dedicated SSH config with the alias `pink-party-backup`, the authorized host and account, absolute credential and known-hosts paths, and `IdentitiesOnly yes`. Verify the host key through an independent channel. The uploader enforces batch mode and strict host-key checks, and disables forwarding and connection multiplexing. Any authentication needed by launchd must work without a prompt. Use the agent's access context when checking files beneath home. Keep protected config outside the checkout, Desktop and any directory that launchd may be denied access to.

## Activate and inspect

Verify the target is empty and dedicated to the lab. Initialize it once before enabling the upload agent. The marker is an application format check. Server-side access control supplies authorization and confinement.

```sh
python3 -B deploy/recovery/offsite.py init "$WRITER_CONFIG"
python3 -B deploy/recovery/launchagent.py install --offsite --config "$WRITER_CONFIG"
python3 -B deploy/recovery/launchagent.py enable --offsite
python3 -B deploy/recovery/launchagent.py inspect --offsite
python3 -B deploy/recovery/offsite.py inspect "$WRITER_CONFIG"
```

The upload agent defaults to a 75-second interval to avoid running in phase with the 60-second collector. It never starts Lima. An attempt has a 110-second process-group limit, 12 seconds per SFTP session, one connection attempt per session and no immediate network retry. Next scheduled ticks retry. Client file and diagnostic output are bounded, and the rolling directory has seven ciphertexts plus one publication slot. The backup job continues to run with the network restrictions from the [Linux units](linux-backups.md).

Inspection reads bounded local history. It shows the original capture time, export time, collection and local validation times, last observed transfer completion, retrieval and full authentication. The capture must be within 20 minutes and the attempt and validation within three minutes. An upload whose rename response was lost can be recovered on a later attempt. Its transfer time is unknown if no successful response was recorded. Polling and reauthentication never renew capture age. A changed or missing latest object is detected on the next attempt. Inspection between ticks reports the last completed observation and does not probe the service. Record an external timestamp separately if the entire Mac is unavailable.

A single pending filename can survive a failed upload. On a later attempt it can be overwritten with a validated source candidate. A final filename keys off the authenticated capture time and archive digest, so repeat runs retrieve the same capture without uploading it again. The worker revalidates the previous success before publishing a different capture. It can remove one older name only after fully authenticating the published replacement. It never deletes the previous success to make room. At capacity with no matching candidate, it fails closed. Unknown files/types, oversized objects and an invalid marker also stop the run.

The SFTP rename, deletion and local history update are separate operations. A lost reply can leave a published object or an already retired old copy. A safe rerun against the same capture revalidates the result. If a newer capture has arrived into a full store, review private results and retrieve an existing candidate before any manual retirement. Record and resolve a corrupt state file before restarting the schedule. Copy it privately before moving it aside. If changing destinations or the SSH config, use a new state directory after preserving evidence. Generic SFTP errors may hide the difference between quota, denied operations and network failures. Review provider-side evidence with the appropriate account without printing secrets.

## Retrieve and rebuild

On the recovery side, use a fresh protected directory and reader JSON with only `version`, `directory` and `sshConfig`. Use the independent read credential and independently obtained age identity. No collection config, source VM, Mac vault or writer state is used for retrieval. Use a new output path in a dedicated 0700 directory. Restrict the temporary identity and ciphertext to the authorized recovery environment.

```sh
python3 -B deploy/recovery/offsite.py list "$READER_CONFIG"
python3 -B deploy/recovery/offsite.py retrieve "$READER_CONFIG" \
  --object "$SELECTED_OBJECT" --identity "$INDEPENDENT_IDENTITY" --output "$CIPHERTEXT"
```

Keep the selected object name in the protected recovery instructions. A direct retrieval by name can recover a good object even if the writer marker or listing is damaged. The command stages ciphertext, authenticates and validates the exact archive, then publishes the local file without overwriting. Deliberate recovery of an older validated capture is allowed. Record its original capture time and how much data might be missing. With a fresh checkout and no other VM running, pass the retrieved ciphertext and explicitly authorized temporary identity to the batch-11 VM helper:

```sh
python3 -B deploy/recovery/prepare-vm.py --batch 11 "$CIPHERTEXT" "$INDEPENDENT_IDENTITY"
limactl shell --workdir=/tmp pink-party-recovery-b11
```

In the clean guest, use the [exact verification variant of the recovery procedure](encrypted-recovery.md#rebuild-a-fresh-guest), with a fresh restore directory such as `batch11-recovered`. Pass `--marker 'Synthetic batch 11: recovered from off-device storage.'` to `verify-recovery.py` and compare the restored bytes privately with the protected exercise evidence. The verifier checks file owners and modes, loaded environment, owned health, the served marker and fresh scheduled monitoring/backup. It does not use the source disk.

## Exercise and clean up

Follow [the batch-10 source preparation and protection steps](scheduled-exports.md#repeat-the-exercise-and-restore-separately) before any redeployment. Begin a new scheduled source exercise with `exercise-scheduled.py begin --batch11 --work-name batch11-chain`. Let the normal timers and both user agents run without manually invoking workers for the measured chain. Record a new capture, export, local validation and remote authenticated retrieval. Preserve the chosen remote object or pause the writer before starting a longer exercise. To test source loss, finish the source exercise, verify original data and fresh normal health, then stop the original guest with the guarded shutdown helper. Disable the uploader before independent retrieval if avoiding rotation of the selected name.

Run faults one at a time in an authorized test area. Use a disposable wrong or unavailable key reference, temporary denied SFTP access, a deliberately unavailable endpoint, or truncated copies in a fixture directory. Preserve all working material first. Use a fixture capacity limit to exercise full storage without consuming the account quota. Observe a new unhealthy attempt, check that the earlier verified material survives, restore access or the fixture, and wait for a successful scheduled retrieval. The local test suite exercises the key, freshness, retention and interruption cases without connecting to a destination.

```sh
python3 -B -m unittest discover -s tests -p offsite_backup_test.py
python3 -B deploy/recovery/launchagent.py remove --offsite
python3 -B deploy/recovery/launchagent.py remove
```

Disable the optional source export schedule. Keep the source disk and protected stores. Before deleting the dedicated disposable recovery guest, save private evidence, stop its project units and use `stop-vm.py pink-party-recovery-b11`. Only delete that task-created instance after the helper records a current VZ stopped event and Lima reports Stopped. Remove temporary recovery inputs according to their custody plan, and preserve the approved independent identity and retained encrypted copies. See the [batch-11 report](offsite-backup-report.md) for local results and the recovery boundary.
