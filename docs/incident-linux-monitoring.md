# Scheduled monitoring: controlled Linux outage

On 16 November 2026, Codex ran this exercise at the owner's request in the local Ubuntu ARM64 VM. The fault was an explicit `systemctl stop pink-party.service`, with no credential or configuration change. No production service or external user was involved. This is assisted project evidence; independent owner incident practice remains unconfirmed.

## Detection and diagnosis

The independent [systemd timer](../deploy/linux/pink-party-monitor.timer) continued running while the application was stopped. Its next scheduled sample changed from `up / web-control-ready` to `down / service-not-active`. Diagnosis found an inactive application unit, no main process and no listeners on TCP 3000/7880 or UDP 7882. The application journal recorded the requested stop and successful deactivation. The monitor timer remained active.

The fault was the deliberate service stop. `Restart=on-failure` correctly left an explicitly stopped service down. Recovery therefore required starting the application, without changing its unit, credentials or restart policy.

## Observed timeline

All timestamps are UTC from the same guest. The [inspected JSON](validation-monitoring.json) retains full precision and the three scheduled samples.

| Time on 16 November 2026 | Observation                                                                   |
| ------------------------ | ----------------------------------------------------------------------------- |
| 18:01:48.780             | Scheduled baseline: web/control ready.                                        |
| 18:01:49.139             | Codex requested the controlled stop.                                          |
| 18:01:49.192             | Stop command completed. The journal recorded successful stop at 18:01:49.190. |
| 18:02:19.774             | Scheduled monitor recorded down.                                              |
| 18:02:20.219             | Status, absent process/listeners and stop journal confirmed the diagnosis.    |
| 18:02:20.220             | Codex requested service start.                                                |
| 18:02:21.345             | Service-owned web/control health verified.                                    |
| 18:02:50.743             | First scheduled recovery sample: web/control ready.                           |

Detection took **30.635 seconds from the stop request**. Owned health was verified **1.125 seconds after the start request**; scheduled recovery was recorded **30.523 seconds after that request**. The interval between down/up samples was 30.969 seconds. The interval from confirmed stop to verified health was 32.153 seconds. These are observed checks, not exact client-perceived outage boundaries or availability guarantees. The timer waits 30 seconds after each completed check, with one-second scheduling accuracy; this run stopped the app immediately after a baseline sample.

## Recovery and verification

The [exercise runner](../deploy/linux/incident.ts) restored the normal service and waited for the timer's recovery observation. It did not manually run the monitor, use a shortened timer or repeat the earlier backend-crash exercises as new evidence. The monitor journal's down/up records matched the saved history. The deployed units passed `systemd-analyze verify`; inspection confirmed separate unit dependencies, root-only history, execution/memory limits and the configured journal retention budget.

The [operations guide](linux-deployment.md#repeat-the-scheduled-incident-exercise) contains the repeatable command, diagnostic commands and cleanup procedure. Raw journals and generated state stay private. The public JSON contains inspected status facts and timestamps, with no generated credentials, host identifiers or raw logs.

Mac and Linux `npm run check` passed TypeScript, 17 offline tests, the production build and formatting. After recovery, all 13 Linux browser cases passed in 42.1 seconds, including decoded synthetic audio both ways and three received streams at each of four clients. The scheduled monitor remained active during this separate media verification. The existing bundle-size warning remains.

A separate [installer regression exercise](../deploy/linux/test-monitor-install.sh) deployed a marked backend startup failure after a successful build. The installer rejected activation, the application reached `failed`, and the active timer recorded a fresh down sample after the installer returned. Redeploying the original source restored owned health and preserved credentials; scheduled recovery was subsequently observed at 18:07:59.751 UTC. This check covers a review finding: monitoring must resume independently of application health after code replacement, including deployment failure cleanup.

## Scope and remaining work

The scheduled probe verifies local web/control readiness through service ownership and the authenticated LiveKit control call behind `/api/health`. Every sample says `media: not-tested`. Actual synthetic audio reception is checked separately by the Linux browser suite. Monitoring records locally; it has no external alert delivery, automatic remediation or outside watchdog, and cannot detect a powered-off VM or its own disabled timer.

Separate-home voice still needs another device/friend. Safari interoperability remains unresolved in the earlier Mac work. Scheduled backups and tested synthetic file restoration were subsequently completed in [batch 6](recovery-linux-backups.md). Cloud deployment remains a later stage. The Mac Tailscale setup and policy were unchanged. Final verification and shutdown facts are recorded in [validation-monitoring.json](validation-monitoring.json).

After normal service and scheduled recovery were verified, Codex stopped the monitor/timer and application for planned shutdown and confirmed their sockets were free. The application and timer remain enabled for the next guest boot. Lima again left a stale host agent waiting; guest poweroff produced the current VZ stopped event at 18:09:27 UTC, before forced host-agent cleanup. The stale stop client and orphaned shutdown helper were also cleared. Final Lima status is `Stopped`. This run does not establish consistently clean Lima host-agent shutdown.
