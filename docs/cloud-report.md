# First private AWS deployment

Recorded 17 November 2026. Codex implemented and exercised this lab at the owner's request. The owner created the AWS Free account, completed temporary CLI and cloud-node sign-in, and approved the temporary network rule and rollback. These are assisted project results, with no claim of independent owner administration, professional cloud duties or a credential.

## Deployment and access

One Ubuntu 24.04 ARM64 `t4g.small` ran in Stockholm with 2 vCPU, 2 GiB RAM and a 12 GiB encrypted gp3 disk. CloudFormation created an isolated network and public SSH access from one administrator `/32`. The application and LiveKit control stayed on loopback. Voice bound only to the new node's Tailscale IPv4; private HTTPS used Tailscale Serve. Cloud credentials were generated on the new host, with no Mac/local-Linux environment or backup transfer.

The live AWS API confirmed an active Free plan with sufficient credit and expiry headroom before provisioning and after deletion. The [costed plan and operations guide](cloud-deployment.md) links provider eligibility, prices and cleanup rules. AWS's [Stockholm price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/20261114012926/eu-north-1/index.csv) gives USD 0.0172/hour for compute and USD 0.0836/GB-month for gp3; [public IPv4](https://aws.amazon.com/vpc/pricing/) adds USD 0.005/hour. Three hours would use about USD 0.07078 before transfer/tax, excluding promotional allowances. No paid upgrade or purchase occurred. Credit balance changes and delayed usage do not establish a final cost.

The Mac reached the real AWS host with normal certificate trust. Two synthetic browser clients passed verified-identity and forged-header checks, Host/Origin/route denials, two WSS 101 upgrades, selected private UDP candidates, decoded audio in both directions, mute/unmute and capture cleanup. A post-call peer ping reported direct transport. The suite passed in 24.3 seconds, then 14.6 seconds after reboot. Both clients ran on one Mac; no new physical listening or separate-home human call is claimed.

## Practical observations

| Exercise on the cloud host                                                        | Observed result                                                                                                          |
| --------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Service permissions, loopback boundaries and rejected configuration in local mode | 22 checks passed; both backend crashes recovered; foreign listener rejected before any kill                              |
| Actual scheduled local-mode backup                                                | 581 ms                                                                                                                   |
| Separate local-mode restore                                                       | 299 ms; exact bytes/modes, working credentials unchanged                                                                 |
| Synthetic file-loss recovery through served data                                  | 1,985 ms                                                                                                                 |
| Scheduled private-mode backup and separate restore                                | Capture observed; restore 298 ms, exact bytes/modes                                                                      |
| Scheduled private-mode outage detection                                           | 30.430 s after explicit stop                                                                                             |
| Owned health after restart                                                        | 1.188 s; scheduled recovery after 30.780 s                                                                               |
| Actual EC2 guest reboot                                                           | Different boot; web/control readiness observed after 29.525 s, with HTTPS/media and fresh timer jobs verified afterwards |

These measurements cover small synthetic files and observed polling intervals. They exclude full provisioning/diagnosis and do not establish recovery or availability guarantees. Recovered credentials were compared in a separate directory and never applied to a fresh machine.

Fresh installation exposed an inactive-unit `reset-failed` error, now avoided by resetting only failed units. Private monitoring exposed Node `fetch` omitting an overridden Host. A real HTTP regression reproduced the 403; bounded native HTTP now preserves the required header. Authentication, CSP and certificate checks stayed intact. Three independent reviews resolved lifecycle, interrupted-state and evidence-scope issues.

Final Mac checks passed 22 TypeScript and 19 Python tests, typecheck, build and formatting. The cloud source check passed 22 TypeScript and 18 Python tests before the final readiness regression was added. The retained local VM earlier passed 19 TypeScript/16 Python tests and 13 browser cases in 40.1 seconds. CloudFormation schema checks passed. The existing bundle-size warning remains. [Inspected validation data](validation-cloud.json) records timing, scope and final-state facts; raw identifiers, credentials, reports and logs stay private.

## Final state and limits

The cloud stack was created at 06:46:49 UTC and deleted at 07:20:22 UTC on 17 November. Before deletion, normal local configuration, fresh scheduled backup/monitoring and owned health were restored; all project services/timers were stopped and the cloud node logged out. The approved policy rollback preserved the original Mac rules.

CloudFormation completed deletion. Independent API queries confirmed the actual root volume, VPC network interfaces, imported key and public-address allocation were absent, with no account-owned snapshots in this region. The instance is terminated; no chargeable lab VM, disk, address, snapshot or network resource remains. The account is still on Free. Historical usage can post later against entitlement. A logged-out Tailscale device listing and certificate-transparency record may remain.

The local VM, application and both timers are stopped, with enabled units, disk and private stores retained. Mac Tailscale remains connected, Serve is empty and project ports are free. Local teardown again required a current guest/VZ stopped event before clearing the stale Lima host agent.

Backups shared the cloud disk and disappeared with this bounded lab. Independent encrypted backup storage, fresh-machine configuration recovery, real uninvited/tagged-source checks, physical client-network recovery and separate-home human voice remain unverified. Safari interoperability remains unresolved.
