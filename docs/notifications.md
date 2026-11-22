<div align="center">

# Notifications

[Docs](README.md) · [Printers](printers.md) · [Cameras](cameras.md) · [Monitoring](monitoring.md) · **Notifications** · [Training frames](feedback.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Writing plugins](plugin-development.md) · [Architecture](architecture.md) · [Troubleshooting](troubleshooting.md)

</div>

Which alert channels PrintGuard supports, what actually gets sent, and how to stop a flaky Wi-Fi camera from blowing up your phone.

- [Set up a channel](#set-up-a-channel)
- [Channels](#channels)
- [What gets sent](#what-gets-sent)
- [Faults and the grace period](#faults-and-the-grace-period)

## Set up a channel

1. Go to **Settings** -> **Alerts**.
2. Switch on a channel and fill in its fields. Every form links straight to that service's setup guide or API docs.
3. Click **Send test alert** (which tests the values currently in the form and attaches a blank image where a real alert attaches a snapshot), then click **Save channels**. If a required field is blank, PrintGuard refuses to save and tells you which field is missing.
4. Saved secrets (keys, tokens, ntfy topic URLs and Discord webhooks) are never shown back in the UI. Their inputs stay blank with "Saved. Leave blank to keep it", and test alerts use the saved value. Type a new value to replace it, or hit **Clear** and save to delete it. Toggling a channel off and back on keeps what you typed until you save. If you change a channel's server address, you'll need to re-enter its saved secrets for safety.
5. Enable **Push notifications** on each monitor you want alerts from (under its **Configure** tab).

Every enabled channel receives every alert, so there's no routing setup to fuss with. A monitor with **Push notifications** off still flags defects and warnings on the dashboard.

## Channels

| Channel | What you need | Notes |
|---|---|---|
| [ntfy](https://ntfy.sh) | A topic URL on ntfy.sh or your own server | No account required. Pick a hard-to-guess topic name, or protect it with an access token. Anyone who knows an open topic URL can read it, so PrintGuard treats the URL like a password and hides it from the UI, bug reports and API. Defect alerts and fault warnings go at urgent priority; recoveries and plugin notices go at normal priority. Self-hosted ntfy servers need [attachments](https://docs.ntfy.sh/config/#attachments) enabled (`attachment-cache-dir` and `base-url`) to receive snapshots |
| [Pushover](https://pushover.net) | An app token from [pushover.net/apps/build](https://pushover.net/apps/build) and your user key | One-off app purchase per platform. Defaults to High priority so alerts cut through device quiet hours; recoveries and plugin notices cap at Normal |
| [Telegram](https://telegram.org) | A bot token from `@BotFather` and your chat ID | You can also set a topic ID (the last number in a link to the topic) to post into a specific topic in a forum group. Recoveries and plugin notices are sent silently |
| [Discord](https://discord.com) | A webhook URL (Server Settings -> Integrations -> Webhooks) | Recoveries and plugin notices are sent silently. Mentions are disabled on all alerts, so naming a monitor `@everyone` won't ping your server |
| Desktop notification | Nothing to configure | Desktop app only. Shows a native OS notification on the machine running the app, even when the window is closed. macOS prompts for notification permission the first time; if notifications are disabled for PrintGuard in system settings, sending fails with an error. Recoveries look the same as other notifications |

Home Assistant receives the same defects and snapshots over MQTT (see [API & MCP](api.md#home-assistant)). If you want periodic print progress updates pushed through these same channels, check out the **Progress reports** [plugin](plugins.md).

## What gets sent

| Notice | Trigger | What's inside |
|---|---|---|
| Defect alert | A defect holds for the monitor's consecutive frame count | Snapshot, risk score and whether PrintGuard paused, cancelled or left the print running. If a pause or cancel failed, it says so clearly |
| Fault warning | A camera disconnects or freezes, a watching monitor has no camera, or a printer stops responding while being watched | Which component failed and whether monitoring stopped or auto-pause is unavailable |
| Recovery | A faulted camera or printer stays healthy again | Sent quietly on channels that support quiet notices (see [Channels](#channels)) |
| Plugin notice | Sent by a [plugin](plugins.md) with `alert:send` permission | The plugin's title and message, no snapshot, sent quietly like a recovery |

If a monitor is set to **Alert only**, the notification makes that clear so you know the print is still running. When PrintGuard tries to pause or cancel a print, it retries up to three times over 45 seconds before reporting failure. Elegoo printers get up to 135 seconds, because a Centauri Carbon 2 waits until its current move finishes before replying. If the printer refuses a pause because the print is already paused or finished (or refuses a cancel because it's already finished), PrintGuard treats that as done.

A monitor's [cooldown](monitoring.md#monitor-settings) holds back the whole defect response (including pause/cancel). On top of that, pushes with the exact same outcome are rate-limited to at least 30 seconds apart per monitor regardless of cooldown, though a successful pause will still push immediately after a failed one.

Long names or messages are truncated with an ellipsis to fit each service's limits: Pushover allows 250 characters for titles and 1024 for messages; Telegram allows 1024 characters with a photo and 4096 without; Discord allows 2000 characters; ntfy allows 250 characters for titles and 4096 bytes for messages.

All enabled channels are notified in parallel with a 30-second timeout each, so one slow or broken service never delays the others or blocks the monitor.

If a channel fails to deliver, PrintGuard raises a dashboard error and does not retry it. Delivery only counts as successful when the service returns its expected response, so a webhook or ntfy URL sitting behind an auth proxy login page is properly flagged as failed. Always include `http://` or `https://` on topic and webhook URLs. If an ntfy server rejects the snapshot attachment, PrintGuard automatically retries the alert as plain text and logs an error on the dashboard explaining that the image was rejected.

Give each channel its final endpoint URL rather than one that redirects. PrintGuard never follows redirects on notification requests; if a URL redirects, the alert (or test alert) fails and tells you the target URL to use instead.

## Faults and the grace period

If a camera dies mid-print and nobody tells you, detection is pointless, so PrintGuard pushes fault warnings for every monitor with **Push notifications** turned on. A few simple guardrails stop that from turning into notification spam:

| Rule | Value |
|---|---|
| How long a fault must last before alerting | **Fault grace period (seconds)** under **Settings** -> **Alerts** (default 2 minutes, configurable from 30 seconds to 15 minutes) |
| When a feed counts as frozen | After 30 seconds with no newly scored frame (the grace period starts from that point) |
| Reminder while a fault stays broken | Every 30 minutes until it recovers |
| How long a feed must stay healthy before sending a recovery | 1 minute initially, doubling after each relapse up to 15 minutes, then resetting to 1 minute after 15 clean minutes |

If you have a Wi-Fi camera that occasionally blips offline and reconnects a few seconds later, bump up the grace period. It can't be switched off completely. Dashboard warnings follow the same grace period; until it expires, only the camera's own status badge shows offline.

What if a camera keeps dropping out and reconnecting just fast enough to reset the grace period every time? PrintGuard catches that too: if a camera has been offline for more than 10% of the last 10 minutes, you get a single unstable-feed warning (skipping the grace period) telling you what percentage of the time it's been dropping, followed by a recovery notice once it settles down. If you see that one, it's usually worth checking the camera's Wi-Fi signal or power supply.

If alerts aren't turning up or are firing too often, check [Troubleshooting](troubleshooting.md#detection-and-alerts).
