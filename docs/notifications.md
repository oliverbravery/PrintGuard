<div align="center">

# Notifications

[Docs](README.md) · [Printers](printers.md) · [Cameras](cameras.md) · [Monitoring](monitoring.md) · **Notifications** · [Training frames](feedback.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Writing plugins](plugin-development.md) · [Architecture](architecture.md) · [Troubleshooting](troubleshooting.md)

</div>

Which channels PrintGuard can alert you through, what it sends, and how to keep a flaky camera
from filling your phone.

- [Set up a channel](#set-up-a-channel)
- [Channels](#channels)
- [What gets sent](#what-gets-sent)
- [Faults and the grace period](#faults-and-the-grace-period)

## Set up a channel

1. Open **Settings**, then the **Alerts** tab.
2. Enable a channel and fill in its form. Each form links the service's own setup guide or API
   reference.
3. Send a test alert from the form, which uses what you typed and carries a blank picture where
   a real alert carries a snapshot, then press **Save channels**.
4. Turn on **Push notifications** on each monitor that should use it.

Every enabled channel gets every notice, so there's no routing to set up. A monitor with
**Push notifications** off still shows everything on the dashboard.

## Channels

| Channel | You need | Notes |
|---|---|---|
| [ntfy](https://ntfy.sh) | A topic URL, on ntfy.sh or your own server | No account needed. Use a hard-to-guess topic, or a protected one with an access token. Anyone with an open topic's URL can read it, so the URL is kept out of bug reports and the API like a password. Every notice is sent at urgent priority. Your own server takes snapshots once [attachments](https://docs.ntfy.sh/config/#attachments) are on, which needs `attachment-cache-dir` and `base-url` set |
| [Pushover](https://pushover.net) | An application token from [pushover.net/apps/build](https://pushover.net/apps/build) and your user key | A one-off app purchase. Priority covers every notice and defaults to High, which bypasses the quiet hours set on the device |
| [Telegram](https://telegram.org) | A bot token from @BotFather and your chat ID | |
| [Discord](https://discord.com) | A webhook URL, from Server Settings, Integrations, then Webhooks | |
| Desktop notification | Nothing | Desktop app only. A native notification on the computer running the app, with the window open or closed |

Home Assistant gets the same defects and snapshots over MQTT, covered in
[API & MCP](api.md#home-assistant). The **Progress reports** [plugin](plugins.md) sends a tally of
a print through these same channels.

## What gets sent

| Notice | When | Carries |
|---|---|---|
| Defect alert | A defect holds for a monitor's consecutive count | A snapshot, the score and whether the print was paused, cancelled or left running. A pause or cancel that failed is called out |
| Fault warning | A camera drops or freezes, or a printer's state can't be read | Which one, and whether the monitor has stopped watching or can no longer pause the print |
| Recovery | A faulted camera or printer has stayed healthy | |

A monitor set to **Alert only** says so in the alert, so you know the print is still running. A
pause or cancel is tried three times before it's reported as failed.

A monitor's [cooldown](monitoring.md#monitor-settings) holds back its whole response to the next
defect, the pause or cancel included. Pushes with the same outcome are also at least 30 seconds
apart for each monitor, whatever the cooldown, so a pause that worked is still pushed straight
after one that failed.

Channels are sent to together and each gets 30 seconds to answer. One that doesn't is reported as
failed and holds up neither the others nor the monitor.

A channel that fails to deliver raises an error on the dashboard. It isn't retried. An ntfy server
that refuses the snapshot is sent the alert again as text, and the dashboard error says the
picture was refused.

## Faults and the grace period

A print nobody is watching is worth hearing about, so faults notify you too, for every monitor
with **Push notifications** on. Three rules keep that from turning into a stream of messages.

| Rule | Value |
|---|---|
| A fault has to last this long before it's pushed | **Fault grace period** in the Alerts tab. Two minutes by default, from 30 seconds to 15 minutes |
| An outage nobody has answered is announced again | Every 30 minutes |
| A recovery is announced once the feed has held | One minute, doubling after each relapse up to 15 minutes, and back to one minute after 15 minutes healthy |

Raise the grace period for a wireless camera that drops out and comes straight back. It can't be
turned off, and the dashboard shows every fault as it happens whatever it's set to.

A camera that reconnects quickly enough to clear the grace period every time gets one warning
for the whole unstable episode, once it has been missing for more than a tenth of the last ten
minutes. It names the share it dropped out for, skips the grace period and has its own notice
when the feed is steady again. That one is worth chasing at the camera.

[Troubleshooting](troubleshooting.md#detection-and-alerts) has the fixes for alerts that never
arrive or arrive too often.
