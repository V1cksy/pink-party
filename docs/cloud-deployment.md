# Private cloud lab operations

Pink Party uses one Ubuntu 24.04 ARM64 EC2 host in Stockholm (`eu-north-1`), running the existing systemd application, monitor and backup units. [The batch-7 report](cloud-report.md) records what actually ran. This lab requires an active AWS **Free account plan**, a separate SSH key and a new Tailscale node. No paid plan or paid upgrade is authorised by these instructions.

## Eligibility and cost

AWS's [Free account plan](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/free-tier-plans.html) provides new-customer credits and closes after six months or when credits run out. Credits on a Paid plan do not prevent charges. [New-signup projects have a selected region](https://docs.aws.amazon.com/accounts/latest/reference/project-regions.html); this account's supported region is Stockholm. Do not activate paid or advanced features to bypass a restriction. Budget alerts are notifications, not spending caps.

The [deployment helper](../deploy/cloud/aws-lab.py) checks the live plan API immediately before provisioning: `FREE`, `ACTIVE`, at least USD 1 credit, at least four hours before plan expiry, and the same account as the authenticated session. An unavailable API, unknown plan, Paid plan or unsupported image fails before creation. Do not substitute a manually edited entitlement file.

Expected list-price credit consumption, using [AWS's regional price list published 14 November 2026](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/20261114012926/eu-north-1/index.csv) and [IPv4 pricing](https://aws.amazon.com/vpc/pricing/):

| Resource                                    | Rate                | Three-hour estimate                |
| ------------------------------------------- | ------------------- | ---------------------------------- |
| `t4g.small`, Linux/shared, 2 vCPU and 2 GiB | USD 0.0172/hour     | USD 0.0516                         |
| 12 GiB gp3 root disk                        | USD 0.0836/GB-month | USD 0.00418, using 720 hours/month |
| One auto-assigned public IPv4               | USD 0.005/hour      | USD 0.015                          |
| Base total                                  |                     | USD 0.07078                        |

This estimate excludes transfer, taxes and currency conversion, and assumes no promotional compute allowance. [EC2 transfer allowances and rates](https://aws.amazon.com/ec2/pricing/on-demand/) depend on destination and account usage. The lab uses one region and no NAT gateway, load balancer, managed database, purchased domain, snapshot or custom KMS key. The disk uses AWS-managed encryption and baseline gp3 settings. CPU credits use `standard`, avoiding unlimited-mode surplus CPU charges. All provisioned resources consume Free-plan entitlement; the estimate is not permission to spend cash or upgrade.

Other inspected options were [Azure for Students](https://azure.microsoft.com/en-us/pricing/offers/ms-azr-0170p/), with USD 100 for 12 months subject to age, full-time study and institutional verification, and [Oracle Always Free](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm), with home-region/resource limits and possible capacity shortages. No student entitlement or Oracle account was confirmed. The owner selected AWS and completed its account onboarding.

## Provision and transfer

Use a current AWS CLI v2 and temporary [browser-based CLI login](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sign-in.html). Do not create static access keys, copy credentials into the repository, or install unrelated integrations. The VM receives no AWS credentials or instance role.

From the Mac checkout:

```sh
mkdir -p .local/cloud
chmod 0700 .local .local/cloud
aws login --profile pink-party-lab --region eu-north-1
python3 deploy/cloud/aws-lab.py preflight
ssh-keygen -t ed25519 -N '' -f .local/cloud/id_ed25519 -C pink-party-lab
python3 deploy/cloud/aws-lab.py create --admin-cidr YOUR_PUBLIC_IPV4/32 --public-key-file .local/cloud/id_ed25519.pub
python3 deploy/cloud/aws-lab.py ssh-config
bash deploy/cloud/deploy.sh
```

Use a lab-only key. Substitute the administrator's current public IPv4; `/0`, wider networks and non-public addresses are rejected. Reuse a retained lab key only after confirming it belongs to this isolated lab. The template creates its own VPC, subnet, internet route, key-pair registration and security group. Public ingress is **SSH 22 from that one `/32` only**. HTTPS, application and media ports are not opened publicly. Outbound traffic supports package downloads and Tailscale, which can use a relay when direct transport is unavailable.

[The template](../deploy/cloud/aws-template.json) fixes the instance/disk size, requires IMDSv2 and deletes the root disk on termination. The helper resolves the [official Canonical image parameter](https://ubuntu.com/aws/docs/aws-how-to/instances/find-ubuntu-images/), checks publisher, architecture, release and disk layout, then records the exact image privately. Node.js and LiveKit retain the Linux installer's pinned SHA-256 checks. No host environment or backup archive is transferred; the cloud installer generates its own credentials.

`ssh-config` trusts the SSH host key only after checking authenticated EC2 console output. When Ubuntu has printed only its generation fingerprint, a scanned key must match that exact fingerprint. It never disables host-key checking. Creation saves state before mutation, uses an idempotency token and retains ambiguous/failure evidence. An interrupted state-write temporary file cannot block later cleanup.

## Enable private access

On the new cloud host only:

```sh
ssh -F .local/cloud/ssh.conf pink-party-cloud
sudo bash /opt/pink-party/app/deploy/cloud/install-tailscale.sh
sudo tailscale up --hostname=pink-party-cloud --accept-dns=false --accept-routes=false --timeout=30s
```

Complete the new node's sign-in in a browser. The [static installer](../deploy/cloud/install-tailscale.sh) verifies the pinned Linux archive and preserves any existing installation. It does not copy Mac Tailscale state or enrol another device automatically.

Privately inspect and save the actual tailnet policy. Add only this cloud node as a destination for the existing invited group on TCP 443 and UDP 7882, with protocol-specific accept/deny tests. Preserve the Mac's hosts, grants, SSH rules and other policy. Use the admin editor's preview and tests before saving. Keep the before/proposal policies private and remove only these cloud entries during rollback. Do not replace the policy with a public example. Tailscale grants are additive.

Create `/etc/pink-party/invited-logins.txt` on the cloud host as a root-owned `0600` file with one actual invited login per line. Then, inside Linux:

```sh
sudo install -o root -g root -m 0644 /opt/pink-party/app/deploy/linux/pink-party-https.service /etc/systemd/system/pink-party-https.service
sudo systemctl daemon-reload
sudo systemctl stop pink-party-https.service pink-party-backup.timer pink-party-backup.service pink-party.service
sudo /opt/pink-party/node/bin/node /opt/pink-party/app/deploy/linux/private-config.ts configure /etc/pink-party/invited-logins.txt
sudo systemctl daemon-reload
sudo systemctl start pink-party.service
sudo /opt/pink-party/node/bin/node /opt/pink-party/app/deploy/linux/service-health.ts
sudo systemctl start pink-party-backup.timer
sudo systemctl enable --now pink-party-https.service
```

Wait for owned health after starting, with bounded retries as in [Linux operations](linux-deployment.md). Do not start HTTPS after a failed check.

Configuration requires a connected native `tailscale0`, matching host address and empty/conflict-free Serve configuration. It saves the existing cloud-local environment for rollback, keeps its cloud-only keys, prepares a root-only monitor request and adds the service's Tailscale startup ordering. Partial setup leaves the saved local file available for inspection and rollback. It never edits tailnet policy.

The app/control sockets remain `127.0.0.1:3000/7880`; LiveKit UDP 7882 binds only to the cloud Tailscale IPv4. Linux Serve runs as root in a separate restricted foreground systemd unit. Stopping it removes its handler. Tagged server destinations are supported; requesting clients still need an untagged user identity. No Funnel, TURN, external STUN, wildcard media bind, certificate exception or CSP change is needed.

The root monitor's `/etc/pink-party-monitor/request.json` holds an exact Host/login pair, without API keys. It uses the trusted loopback boundary; this probe does **not** verify a remote identity, TLS or media. Application request authentication stays in place.

## Repeat the exercises

Close room clients and run disruptive service exercises sequentially. On a freshly installed cloud host in local mode, use the [Linux verifier](../deploy/linux/verify.ts) and [backup exercise](../deploy/linux/exercise-backup.py) before private setup. They test service permissions, crashes, rejected configuration, scheduled backups and synthetic file-loss recovery. Their local-mode labels describe access mode; the AWS host must be established separately through provider evidence.

In private mode, inside Linux:

```sh
sudo bash /opt/pink-party/app/deploy/cloud/check-private.sh
```

This checks native-interface and cgroup-owned sockets, waits for a matching scheduled private backup, restores both files into a new separate directory, verifies bytes/modes, then runs the scheduled controlled outage and recovery. It does not apply recovered credentials or prove sound. Reports stay under the root-only backup/restore and monitor directories.

From the Mac:

```sh
bash deploy/cloud/check.sh
python3 deploy/cloud/aws-lab.py reboot-check
PINK_PARTY_CLOUD_TARGET=.local/cloud/target.json npm run test:tailnet
```

Create that private target JSON from the cloud node's observed values, with exactly `origin` and `tailscaleIp`. It contains no application credentials. The real-Serve suite checks that the client and server addresses differ before recording cross-host evidence. It checks normal certificate trust, replaced forged identity, denied Host/Origin/routes, actual WSS upgrades, selected private UDP candidates, decoded synthetic audio, mute/unmute and capture cleanup.

The isolated source-check workspace installs its own dependencies so Vite cannot write into the root-owned working deployment. `reboot-check` verifies a different guest boot, automatic app/HTTPS/timer startup and unchanged configuration, without manually starting units. Recheck fresh scheduled samples and media after reboot. Keep raw reports, screenshots, tokens, identities, addresses and journals private.

## Rollback and destroy

Keep the original local VM and Mac setup. On the cloud host, close clients, stop/disable `pink-party-https.service`, stop the application and backup units, then run:

```sh
sudo /opt/pink-party/node/bin/node /opt/pink-party/app/deploy/linux/private-config.ts rollback
sudo systemctl daemon-reload
sudo systemctl start pink-party.service pink-party-backup.timer
sudo /opt/pink-party/node/bin/node /opt/pink-party/app/deploy/linux/service-health.ts
```

Verify normal local-mode health and original cloud credentials. Remove only the temporary cloud policy host/grant/tests after comparing with the saved policy. Stop the application, both timers, both oneshots and HTTPS, then `sudo tailscale logout` on the **cloud** host. Never reset Serve or log out Tailscale on the Mac. A logged-out cloud device listing and public certificate-transparency record may remain; neither runs a cloud VM.

From the Mac, while temporary AWS access is still valid:

```sh
python3 deploy/cloud/aws-lab.py destroy
python3 deploy/cloud/aws-lab.py status
```

Deletion works independently of Free-plan eligibility. It checks the account and stack ownership, attempts deletion even when pre-delete inventory fails, waits for `DELETE_COMPLETE`, then requires terminated lab instances and empty tagged volume, snapshot, address and VPC inventories. Review the saved root-volume/ENI identifiers separately if a tag or resource was changed manually. The auto-assigned public IPv4 is released with instance/network-interface termination. No snapshot or retained-disk policy is configured.

Powering off EC2 alone leaves disk costs. A failed/ambiguous delete, expired CLI session or remaining inventory is incomplete cleanup: sign in again, inspect the private state/events and retry. For manual recovery, use the recorded unique stack ID with `aws cloudformation delete-stack`, then verify the actual resources. Never retain resources to work around deletion failure. Preserve completed private state for review; the next creation archives a verified completed state.

Billing and credit usage can lag deletion. Recheck the Free-plan API and billing console; empty resource inventory does not prove that the final historical usage amount has posted. Same-disk backups disappear with this lab's disk. Independent encrypted backup storage, fresh-machine credential recovery, separate-home human audio and Safari interoperability remain outside the completed scope.
