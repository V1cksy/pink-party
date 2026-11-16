# Linux deployment validation

Recorded 16 November 2026. Codex installed, configured and exercised this deployment at the owner's request. Independent owner operation or understanding has not been observed. This is a local systems-administration lab with [repeatable instructions](linux-deployment.md).

## Environment

Lima 2.3.0 with macOS VZ; Ubuntu 24.04.5 LTS ARM64, kernel 6.8.0-147-generic and systemd 255. The VM has two CPUs, 1536 MiB RAM and a 12 GiB sparse disk. Node.js 24.22.2 and LiveKit 1.13.11 came from checksum-verified release archives.

Shared host folders, application port forwarding and containerd are disabled. Pink Party sockets are guest-loopback only. Linux credentials are separate from the Mac's settings. Native Tailscale policy and Serve configuration were not changed.

## Service exercises

The [verification script](../deploy/linux/verify.ts) checks the actual service and processes. Inspected results are in [validation-linux.json](validation-linux.json).

- The supervisor has a dedicated non-root effective UID, no effective capabilities and `NoNewPrivs` enabled.
- Service code and synthetic session data are root-owned and not writable by the service. Credentials are root-only. State is service-owned mode `0700`; generated LiveKit configuration is mode `0600`.
- App/control TCP 3000/7880 and media UDP 7882 listen only on guest loopback.
- Killing either backend causes the supervisor to stop the group and systemd to start a healthy replacement.
- Manual stop releases all sockets and stays stopped; normal startup restores health.
- A temporary unrelated HTTP listener is rejected by the health/ownership checks before any kill. Installation and crash exercises require the listening process to belong to the actual service cgroup.
- Invalid credentials reject startup with closed ports and an explanatory journal message. The checked invocation did not log the actual API secret or join code. The temporary override is removed and normal configuration restored.

Unsuitable verifier invocations are rejected before service commands. An offline regression test injects root/platform/tool fixtures and checks this boundary. Inserting a service command before configuration validation made the test fail as expected, with that command blocked by the fixture. Cleanup attempts are independent so one failure does not skip remaining recovery steps or report writing.

## Browser and application checks

All 13 browser cases passed inside the VM in 39.3 seconds. Headless Chromium used generated microphone audio against the systemd deployment. Checks covered received bytes, decoded samples and positive audio energy both ways, four-client media and capacity, mute/unmute, leave/rejoin, token rejection, microphone failures, playback recovery and signaling interruption. All clients were within one VM.

TypeScript, all 15 offline tests, the production build and formatting passed in Linux and on the Mac. The existing bundle-size warning remains. The initial transfer omitted the formatter configuration; the format check caught this, and the transfer manifest now includes formatter and npm/Node settings. The corrected full check passed before the browser suite.

## Installation and guest boot

The [installer exercise](../deploy/linux/test-install.sh) verified that an intentionally failed build, identified by its marker and exit status, left the original process healthy. A subsequent successful deployment from a source tree containing synthetic `.env`, `.env.private`, nested `.env.production` and `.local` files excluded those files, retained the existing Linux credentials and replaced the running service. Existing code and runtimes remained available in the previous-version directory.

A complete Lima guest stop/start changed the Linux boot ID. The enabled service became healthy without an explicit service-start command; guest stop/start and the health check took 12.88 seconds. This is guest reboot evidence, not a Mac reboot claim.

Final teardown exposed a Lima lifecycle issue: `limactl stop` waited with its host agent still running. Pink Party had already stopped and released its sockets. Guest `systemctl poweroff` produced the VZ stopped event and removed the host VM process; forced Lima cleanup then cleared the stale host agent. The final VM status is Stopped, with configuration retained. The [operations guide](linux-deployment.md) records this fallback; normal host-agent shutdown is not consistently established by this run.

## Resource samples

The service cgroup averaged 123.29 MiB over ten idle samples, including the supervisor, app, LiveKit and charged cache. This excludes Chromium, the guest OS and host VM overhead. During four-client synthetic media, separate process samples averaged 115.31 MiB RSS for the app and 99.92 MiB for LiveKit. These measures have different accounting scopes and must not be added or compared as equivalent memory totals.

Host Lima/Virtualization process samples are recorded separately in the JSON report. Configured guest RAM remains 1536 MiB; host RSS is not the VM's total memory cost. No performance improvement is claimed.

## Startup diagnosis

The initial hardened unit permitted Unix, IPv4 and IPv6 sockets. LiveKit exited with `netlinkrib: address family not supported by protocol`; the supervisor exited and systemd's restart limit stopped repeated attempts. The journal identified failed interface enumeration. Adding `AF_NETLINK` resolved startup. Network-administration capabilities remain absent, and subsequent socket checks confirmed loopback binding.

## Limits

This provides a tested Linux deployment and service-recovery record. It does not establish professional Linux experience, owner-performed deployment, cloud deployment or physical audio on Linux. Linux Tailscale/HTTPS and calls from another device remain untested. Earlier Mac private-network evidence is in [batch 3](validation-batch-3.md).

Scheduled monitoring and a controlled incident exercise were subsequently completed in [batch 5](incident-linux-monitoring.md), with separate [inspected data](validation-monitoring.json). The earlier crash and invalid-configuration checks above remain batch-4 evidence. Tested backup restoration and cloud deployment remain future work. Public evidence omits generated credentials, VM identifiers and private logs.
