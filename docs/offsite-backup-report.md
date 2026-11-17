# Batch 11: encrypted SFTP backup preparation

I added a scheduled SFTP stage after authenticated Mac collection. It keeps up to seven encrypted copies plus a publication slot, verifies both the staged and final remote object by download and complete age authentication, and records capture time separately from transfer and retrieval. A separate reader command uses its own SSH config and explicit recovery identity. [Setup, schedules and recovery commands](offsite-backups.md)

## Observed checks

| Exercise                                      | Observation                                                                                                                                                                                                                                                                                                                                    |
| --------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Local OpenSSH SFTP fixture                    | Real SFTP upload, retrieval, publication and retirement commands ran against a test directory on the Mac. Repeated validation of the same capture kept one object and preserved its capture and transfer timestamps.                                                                                                                           |
| Restore with collection inputs unavailable    | I moved the fixture's rolling store aside and removed its collection configuration. The independent reader retrieved from SFTP. Recovery reproduced both synthetic files byte for byte with the expected modes in a separate directory.                                                                                                        |
| Interrupted transfer and publication          | Injected partial upload and lost rename response cases preserved prior material. The retry cleaned the partial upload or verified the already published object. Where a rename response was lost, transfer time stayed unknown.                                                                                                                |
| Unavailable, denied, corrupt and stale inputs | The real local SFTP process failed against a missing directory. Injected access and quota errors, missing or changed ciphertext, wrong or unavailable keys, full retention, corrupt state, stale capture and overlapping jobs kept health false. Independent retrieval rejected truncated ciphertext and a wrong key before publishing output. |
| Live launchd failure                          | A temporary user agent ran with a valid synthetic collection and an unreachable loopback SFTP endpoint. The worker recorded failure in 2.254 seconds. The observation arrived 18.013 seconds after agent enablement with a 15-second exercise interval. The fixture agent was then removed.                                                    |

## Portfolio scope and retained state

I closed batch 11 at local validation. The public ARM64 implementation check passed 22 TypeScript tests, 66 Python tests and 13 synthetic browser cases with zero uploaded artifacts. [Implementation check](https://github.com/V1cksy/pink-party/actions/runs/44168716981)

At closeout, the pinned export and all seven rolling copies authenticated again. The source VM stayed stopped with its disk and protected stores retained. Both Mac user agents were unloaded and uninstalled.

The fixture verifies SFTP publication and exact file restoration on one Mac. A successful scheduled transfer to off-device storage and a fresh guest recovered using independently held credentials and identity remain unverified. The retained ciphertext and identity still share one physical Mac.
