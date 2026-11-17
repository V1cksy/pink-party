# Encrypted export and fresh Linux recovery

For automatic encryption, authenticated Mac collection and freshness checks, use [scheduled exports](scheduled-exports.md). That workflow uses a separate rolling area and preserves this manually managed vault/key. The manual commands below remain available.

This workflow keeps a validated snapshot outside the source VM, encrypted with [age](https://github.com/FiloSottile/age). It rebuilds a separate local Ubuntu ARM64 guest from public source and applies only the recovered Linux local-mode session and application environment. [The batch-8 report](recovery-off-vm.md) records what actually ran.

## Storage and key boundary

The source guest receives one native X25519 **public recipient**. Its private recovery identity stays outside the guest and vault. Use owner-only `0700` directories and `0600` key, recipient and ciphertext files. The disposable recovery guest receives a temporary identity copy through administrative SSH; its disk is deleted after evidence collection. Never transfer a Mac environment, AWS credentials, Tailscale state or a cloud configuration.

The first vault and key live in separate protected directories on the same physical Mac. This protects the exercise against losing access to the original VM/disk image. It does not survive loss of that Mac disk/host, an administrator who can read both locations, malware running as the owner, deletion of both copies, or loss of the only key. Off-device storage and a separately held key copy remain future work. File permissions are access controls, not encryption of the identity itself. Secure deletion of temporary plaintext on SSDs is not claimed.

age provides encrypted-file authentication, including rejection of an incomplete final chunk; the implementation waits for successful decryption before parsing any plaintext. The [age format](https://age-encryption.org/v1) defines this boundary. Anyone with the public recipient can create an encrypted file. Successful decryption therefore establishes compatibility and ciphertext integrity, **not the sender's identity, freshness or provenance**. The archive's internal SHA-256 values check consistency; recomputing the outer checksum after decryption adds no provenance. Select recovery material from a trusted private store and a reviewed source revision. Encryption cannot make a compromised source trustworthy, prevent rollback to an older valid copy or rotate exposed credentials.

## Prepare private storage

On the Mac, install age through Homebrew. Generate the key once, with its output redirected privately; do not overwrite an existing identity. These example paths are outside the repository and Lima storage:

```sh
brew install age
umask 077
KEY_DIR="$HOME/.config/pink-party-recovery"
VAULT="$HOME/Library/Application Support/PinkPartyRecovery/vault"
mkdir -p "$KEY_DIR" "$VAULT"
chmod 0700 "$KEY_DIR" "$VAULT"
age-keygen -o "$KEY_DIR/recovery.agekey" 2>"$KEY_DIR/keygen.log"
age-keygen -y "$KEY_DIR/recovery.agekey" >"$KEY_DIR/recipient.txt"
chmod 0600 "$KEY_DIR/"*
```

Keep the identity available through review and future recovery. A missing/wrong-key exercise uses a missing reference or a different temporary identity; never delete the retained working key. The source needs only `recipient.txt`. Copy it with `limactl copy`, install it root-owned as `/var/lib/pink-party-export-config/recipient.txt` beneath a root-owned `0700` directory, then remove the transfer file. Do not print its contents or real archive names in public evidence.

## Capture, encrypt and collect

First preserve the source's original session, environment and known-good snapshots beneath `/var/lib/pink-party-restores`, outside routine retention. Stop its backup timer and oneshot before those copies or deployment. A redeployment replaces the installed session with the source-controlled file: reinstall the protected original session and compare the environment privately before running exercises.

The existing backup unit and its `PrivateNetwork=true`/`AF_UNIX` restrictions are unchanged. Install Ubuntu's `age` package separately. Create root-only export/config directories. With a healthy local deployment, run this sequential exercise inside the source guest:

```sh
sudo install -d -m 0700 /var/lib/pink-party-exports /var/lib/pink-party-export-config
sudo apt-get install -y --no-install-recommends age
sudo timeout 240s python3 -B /opt/pink-party/app/deploy/linux/exercise-export.py /var/lib/pink-party-export-config/recipient.txt
```

The runner saves original files privately, serves a clearly labelled synthetic marker, observes an actual normal-timer capture, protects that capture from retention and encrypts it. Cleanup restores the original session, checks unchanged credentials, and waits for a matching normal scheduled backup and scheduled monitoring recovery. Its private report identifies the completed encrypted export. After interruption, inspect `/run/pink-party-verification.lock`, timer states and `/var/lib/pink-party-restores/export-exercise-*` before removing a stale lock or resuming work. Do not blindly apply an environment as a data-recovery fix.

For ordinary export of a selected completed capture, inside Linux:

```sh
sudo timeout 45s python3 -B /opt/pink-party/app/deploy/linux/encrypted-backup.py export /var/lib/pink-party-backups/BACKUP_NAME /var/lib/pink-party-exports --recipient-file /var/lib/pink-party-export-config/recipient.txt
```

This locks capture retention and export publication, validates the original snapshot with [backup.py](../deploy/linux/backup.py), then encrypts its tar before transfer. Snapshot bounds remain 16 KiB per input and 64 KiB per archive. age output is capped at 128 KiB with a 15-second process timeout and file-size limit; application validators each have a five-second timeout. No plugins, SSH identities or interactive passphrases are accepted. A verified staging file is synced before atomic directory publication. Only after publication may the guest prune to seven completed exports, always retaining the new copy despite clock rollback. Failure before publication leaves prior copies untouched. A pruning/sync failure after publication can leave a valid new copy or extra old copies; inspect state privately before retrying.

From the Mac checkout, substitute the private completed export name:

```sh
python3 deploy/recovery/vault.py pink-party EXPORT_NAME "$VAULT"
mkdir -m 0700 "$KEY_DIR/verify-work"
python3 deploy/linux/encrypted-backup.py verify "$VAULT/EXPORT_NAME.age" --identity-file "$KEY_DIR/recovery.agekey" --work-dir "$KEY_DIR/verify-work"
```

The collector transfers only the fixed ciphertext filename, with a 30-second timeout and 128 KiB limit. Its non-blocking lock serializes collection; completed files publish atomically with mode `0600`. Interrupted collection stages are removed by the next locked collection. The Mac vault refuses an eighth completed copy and never automatically deletes recovery material. Authenticate and validate a replacement and retain a tested copy before manually retiring older files. A header check during transfer is not authentication; `verify` must succeed before recovery.

## Rebuild a fresh guest

Stop all source application/monitor/backup units first, verify normal data and retained copies privately, then stop the original guest. [stop-vm.py](../deploy/recovery/stop-vm.py) tries normal shutdown, requests guest poweroff when necessary, and permits stale Lima cleanup only after a **new current** VZ stopped event. It refuses cleanup without that evidence. Confirm the stopped source cannot run `limactl shell`.

Run from a reviewed checkout, with the original guest stopped and no existing `pink-party-recovery-b8` instance:

```sh
python3 deploy/recovery/stop-vm.py pink-party
python3 deploy/recovery/prepare-vm.py "$VAULT/EXPORT_NAME.age" "$KEY_DIR/recovery.agekey"
limactl shell --workdir=/tmp pink-party-recovery-b8
sudo bash /root/pink-party-source/deploy/linux/recovery-install.sh /root/pink-party-source /var/lib/pink-party-restores/input/snapshot.age /var/lib/pink-party-restores/key/recovery.agekey
```

The helper creates an independent disk from the checksum-pinned Ubuntu image using [lima.yaml](../deploy/linux/lima.yaml): two CPUs, 1536 MiB RAM, 12 GiB sparse disk, no shared host folders and no application port forwarding. It never clones or mounts the original disk. It transfers the public manifest only, the ciphertext and a temporary key copy. Administrative localhost SSH remains available. Run one guest at a time on an 8 GiB Mac.

[recovery-runtime.sh](../deploy/linux/recovery-runtime.sh) installs age/Python and a checksum-pinned private Node validator. [runtimes.sh](../deploy/linux/runtimes.sh) is the single source for the Node/LiveKit download pins. Ubuntu package verification and the npm lockfile remain part of the software-supply boundary. Recovery needs network access to rebuild software; this is not an offline bare-metal image.

The wrapper decrypts and validates into a new private directory beneath the monitor-excluded restore store, then invokes `install.sh SOURCE --recover-from DIRECTORY`. It removes its temporary restored files on exit. For the exact comparisons used in this exercise, use the following separate steps **instead of the wrapper**, inside the fresh guest:

```sh
sudo bash /root/pink-party-source/deploy/linux/recovery-runtime.sh
sudo env PATH=/var/lib/pink-party-recovery-tools/node/bin:/usr/bin:/bin python3 -B /root/pink-party-source/deploy/linux/encrypted-backup.py restore /var/lib/pink-party-restores/input/snapshot.age /var/lib/pink-party-restores/batch8-recovered --identity-file /var/lib/pink-party-restores/key/recovery.agekey --work-dir /var/lib/pink-party-restores/decrypt-work
sudo bash /root/pink-party-source/deploy/linux/install.sh /root/pink-party-source --recover-from /var/lib/pink-party-restores/batch8-recovered
```

The installer revalidates the exact file set, application schema, ownership/modes and **local-only** configuration. It stages recovered session data into the build and installs the recovered environment after build success. Existing app/config/state/units and symlinked destinations are rejected before network activity; an installation lock serializes activation. No setup command or generated replacement key is needed.

`restore` requires a new destination beneath a private parent and a separate `--work-dir`. It fully decrypts, authenticates and reuses exact archive/path/type/schema validation before writing fixed allowlisted files. Existing destinations, wrong/missing keys, invalid modes, corruption and invalid payloads fail without applying anything. Kill/interruption can leave root-only staging; the next locked operation removes its own decrypt staging. A lower-level interrupted restore may leave `.restore-*`; inspect/remove it only when no restore is running. The healthy installation is never a restore destination.

## Verify and remove only the disposable guest

With a retained separate restore directory, run inside recovery Linux, sequentially:

```sh
sudo python3 -B /opt/pink-party/app/deploy/linux/verify-recovery.py /var/lib/pink-party-restores/batch8-recovered /var/lib/pink-party-restores/verification-report.json
sudo python3 -B /opt/pink-party/app/deploy/linux/exercise-encrypted.py /var/lib/pink-party-restores/input/snapshot.age /var/lib/pink-party-restores/key/recovery.agekey
sudo bash /opt/pink-party/app/deploy/linux/test-recovery-install.sh
sudo /opt/pink-party/node/bin/node --env-file=/etc/pink-party/pink-party.env /opt/pink-party/app/deploy/linux/verify.ts
sudo bash /opt/pink-party/app/deploy/linux/test.sh
```

The verifier compares installed bytes/modes privately, checks the service process actually loaded recovered credentials, owned health, served marker and active/enabled units, then observes fresh normal scheduled jobs. It restarts the normal backup timer, without manually invoking its oneshot. The encrypted exercise tries missing/wrong/unavailable key references, corrupt/truncated input, authenticated invalid archive/schema/path, existing destinations, failed export permissions and actual CLI process-group interruptions with a blocking age stand-in. It compares healthy files, process, owned health and prior good ciphertexts. Tests also inject post-validation restore write/publication failures. Browser checks establish received/decoded synthetic audio separately from HTTP health.

Copy only reviewed raw reports/logs into private Mac evidence storage; leave recovered plaintext inside the guest. Close clients, stop the application, both timers and both oneshots, and verify released sockets. Then, from the Mac:

```sh
python3 deploy/recovery/stop-vm.py pink-party-recovery-b8
limactl delete --force pink-party-recovery-b8
limactl list
```

Delete only this task-created disposable instance after confirming it is stopped and evidence is retained. Keep the original `pink-party` VM, its disk/stores, the Mac ciphertext and separately protected recovery key. Verify those retained files remain readable with restrictive modes and authenticate the retained ciphertext again. No AWS resource or Tailscale change is involved in this stage.
