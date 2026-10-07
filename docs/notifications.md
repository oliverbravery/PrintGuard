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
3. Press **Send test alert**, which uses what you typed and carries a blank picture where a real
   alert carries a snapshot, then press **Save channels**. A channel with a starred field left
   blank isn't saved, and the error names the field.
4. A saved key, token, topic URL or webhook is never shown again. Its field is empty and reads
   "Saved. Leave blank to keep it", and a test alert uses the saved one. Type in it to replace
   the saved one, or press **Clear** and save to remove it. Switching a channel off and on again
   keeps what you typed until you save. Changing a channel's address needs its saved secrets typed
   again.
5. Turn on **Push notifications** on each monitor that should use it.

Every enabled channel gets every notice, so there's no routing to set up. A monitor with
**Push notifications** off still shows everything on the dashboard.

## Channels

| Channel | You need | Notes |
|---|---|---|
| [ntfy](https://ntfy.sh) | A topic URL, on ntfy.sh or your own server | No account needed. Use a hard-to-guess topic, or a protected one with an access token. Anyone with an open topic's URL can read it, so the URL is kept out of the dashboard, bug reports and the API like a password. Defect alerts and fault warnings are sent at urgent priority, and recoveries and a plugin's notices without it. Your own server takes snapshots once [attachments](https://docs.ntfy.sh/config/#attachments) are on, which needs `attachment-cache-dir` and `base-url` set |
| [Pushover](https://pushover.net) | An application token from [pushover.net/apps/build](https://pushover.net/apps/build) and your user key | A one-off app purchase. Priority defaults to High, which bypasses the quiet hours set on the device. Recoveries and a plugin's notices go at Normal at most |
| [Telegram](https://telegram.org) | A bot token from @BotFather and your chat ID | Recoveries and a plugin's notices are sent without a sound |
| [Discord](https://discord.com) | A webhook URL, from Server Settings, Integrations, then Webhooks | Recoveries and a plugin's notices are sent with notifications suppressed |
| Desktop notification | Nothing to fill in | Desktop app only. A native notification on the computer running the app, with the window open or closed. macOS asks for permission the first time, and a send fails with an error while notifications are switched off for PrintGuard in the system settings. A recovery looks like any other notice |

Home Assistant gets the same defects and snapshots over MQTT, covered in
[API & MCP](api.md#home-assistant). The **Progress reports** [plugin](plugins.md) sends a tally of
a print through these same channels.

## What gets sent

| Notice | When | Carries |
|---|---|---|
| Defect alert | A defect holds for a monitor's consecutive count | A snapshot, the score and whether the print was paused, cancelled or left running. A pause or cancel that failed is called out |
| Fault warning | A camera drops or freezes, a watching monitor has no camera, or a printer's state can't be read while its monitor watches | Which one, and whether the monitor has stopped watching or can no longer pause the print |
| Recovery | A faulted camera or printer has stayed healthy | Sent quietly where the channel has a way to, as the [channels](#channels) say |
| Plugin notice | A [plugin](plugins.md) granted `alert:send` sends one | Its own title and text and no snapshot, sent quietly like a recovery |

A monitor set to **Alert only** says so in the alert, so you know the print is still running. A
pause or cancel is tried up to three times in 45 seconds before it's reported as failed. An
Elegoo printer gets 135 seconds, since a Centauri Carbon 2 answers only once it has finished
moving. A pause the printer refuses counts as done when the print is already paused or over, and
a cancel when it's already over.

A monitor's [cooldown](monitoring.md#monitor-settings) holds back its whole response to the next
defect, the pause or cancel included. Pushes with the same outcome are also at least 30 seconds
apart for each monitor, whatever the cooldown, so a pause that worked is still pushed straight
after one that failed.

A name or message longer than a service takes is cut with an ellipsis. Pushover takes a 250
character title and a 1024 character message, Telegram a 1024 character caption, Discord 2000
characters and ntfy 4096 bytes.

Channels are sent to together and each gets 30 seconds to answer. One that doesn't is reported as
failed and holds up neither the others nor the monitor.

A channel that fails to deliver raises an error on the dashboard. It isn't retried. An ntfy server
that refuses the snapshot is sent the alert again as text, and the dashboard error says the
picture was refused.

Give a channel the address it answers on, not one that redirects to it. A redirect is never
followed, so the alert, or the test alert, fails and names the address to use.

## Faults and the grace period

A print nobody is watching is worth hearing about, so faults notify you too, for every monitor
with **Push notifications** on. These rules keep that from turning into a stream of messages.

| Rule | Value |
|---|---|
| A fault has to last this long before it's announced | **Fault grace period (seconds)** in the Alerts tab. Two minutes by default, from 30 seconds to 15 minutes |
| A feed counts as frozen | After 30 seconds without a scored frame, and the grace period starts then |
| A fault that is still there is announced again | Every 30 minutes for as long as it lasts |
| A recovery is announced once the feed has held | One minute, doubling after each relapse up to 15 minutes, and back to one minute after 15 minutes healthy |

Raise the grace period for a wireless camera that drops out and comes straight back. It can't be
turned off. The dashboard's warning waits for it too, and until then only the camera's own
status reads offline.

A camera that reconnects quickly enough to clear the grace period every time gets one warning
for the whole unstable episode, once it has been missing for more than a tenth of the last ten
minutes. It names the share it dropped out for, skips the grace period and has its own notice
when the feed is steady again. That one is worth chasing at the camera.

[Troubleshooting](troubleshooting.md#detection-and-alerts) has the fixes for alerts that never
arrive or arrive too often.
