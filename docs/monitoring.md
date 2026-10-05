<div align="center">

# Monitoring and tuning

[Docs](README.md) · [Printers](printers.md) · [Cameras](cameras.md) · **Monitoring** · [Notifications](notifications.md) · [Hardware](hardware.md) · [Deployment](deployment.md) · [API & MCP](api.md) · [Plugins](plugins.md) · [Writing plugins](plugin-development.md) · [Architecture](architecture.md) · [Troubleshooting](troubleshooting.md)

</div>

A monitor binds a camera to an optional printer and decides when a defect is real and what to do
about it. This page covers its settings, the camera settings that change what the model sees, and
the risk history you tune them against.

- [How a defect becomes an alert](#how-a-defect-becomes-an-alert)
- [Monitor settings](#monitor-settings)
- [When a monitor watches](#when-a-monitor-watches)
- [Tuning the camera](#tuning-the-camera)
- [Risk history](#risk-history)
- [Choosing values](#choosing-values)

## How a defect becomes an alert

```mermaid
flowchart LR
    frame["Camera frame<br/>rotated, cropped, adjusted"] --> score["Score 0 to 1"]
    score --> over{"At or above<br/>the threshold?"}
    over -- "No" --> reset["Streak resets"]
    over -- "Yes" --> streak{"Enough frames<br/>in a row?"}
    streak -- "No" --> frame
    streak -- "Yes" --> act["Alert, then pause or cancel"]
    act --> cool["Cooldown"]
```

The score is the model's own confidence that the frame shows a failing print, so 0.5 is where it
changes its mind. One bad frame does nothing. A defect has to hold for a run of frames before the
monitor acts, and the cooldown keeps one failure from alerting twice.

## Monitor settings

Open a monitor from the dashboard to change these. They save as you move them.

![A monitor's panel: live risk, printer controls, temperatures, preheat presets and the monitoring settings](assets/printer-detail.png)

| Setting | Default | Range | What it does |
|---|---|---|---|
| **Watch this monitor** | On | | Turns the monitor off without deleting it |
| **Alert threshold** | 0.75 | 0.05 to 1 | The score a frame has to reach to count as a defect |
| **Consecutive detections to alert** | 3 | 1 to 30 | How many flagged frames in a row it takes to act |
| **On sustained defect** | Alert only | | Alert only, pause the print or cancel the print. The last two need a linked printer |
| **Cooldown** | 60 seconds | 0 to 600 | The quiet gap after acting before the monitor can act again |
| **Push notifications** | Off | | Sends this monitor's alerts and warnings to your [alert channels](notifications.md) |

> [!IMPORTANT]
> A new monitor only shows a defect on the dashboard. Turn on **Push notifications** to hear about
> it, and choose pause or cancel if you want the print stopped.

The same panel pauses, resumes or cancels the print by hand, and sets the printer's
[temperatures](printers.md#temperatures-and-preheat).

## When a monitor watches

A monitor with no printer watches all the time. A monitor with a printer watches while the
printer reports that it's printing, and stands down when it reports idle, paused or an error.
Losing contact with the printer keeps whatever it last reported, so a printer that drops off
mid-print is still watched. [Failing safely](architecture.md#failing-safely) has the reasoning.

## Tuning the camera

These settings live on the camera, under **Cameras**, so every monitor using that camera gets
them. They apply to the live view, the frames the model scores, the snapshots in your alerts and
the frames the [API](api.md) returns.

| Setting | Default | Range | What it does |
|---|---|---|---|
| **Rotation** | 0° | 0°, 90°, 180°, 270° | Sets a camera mounted sideways or upside down upright |
| **Crop** | The middle square | Any square | The part of the view the model watches |
| **Brightness** | 1 | 0.25 to 2 | Lifts a dim chamber or tames a bright one |
| **Contrast** | 1 | 0.25 to 2 | Separates the print from a background of a similar shade |
| **Sharpness** | 0 | 0 to 2 | Brings out strands on a soft camera |
| **Detection rate** | 60 a second | 0.1 to 60 | The most frames a second the model scores from this camera |

The model only watches a square of each camera's view. Until you crop a camera that square is the
middle of the frame, so on a wide camera the sides of the bed go unwatched. Crop it to a square
the print fills. Rotation is applied first, so you draw the crop on the picture as you see it.

Detection normally runs as often as the hardware and the camera allow. Lower **Detection rate**
to cut the load PrintGuard puts on a shared host. A defect takes longer to confirm at a lower
rate, since the consecutive count is in frames.

## Risk history

A monitor's panel shows the live score on a gauge beside the last few minutes of it.
**View detailed history** opens the full page.

| Part | Shows |
|---|---|
| Risk per period | The score charted over the last hour, 6 hours, 24 hours or everything kept |
| Risky moments | A snapshot of what the camera saw each time the monitor raised an alert |

History is kept in memory as one-minute buckets covering the last 24 hours, with the latest 40
snapshots and 50 alerts for each monitor. Restarting the hub clears it. The
[REST API](api.md#rest-api) serves the same history and snapshots.

## Choosing values

Start with the defaults and one real print, then read the history.

| You see | Change |
|---|---|
| Alerts on a good print | Raise the threshold, or raise the consecutive count so brief blips are ridden out |
| A failure caught late | Lower the threshold or the consecutive count |
| A failure that barely moves the score | Crop the camera so the print fills the square, then check the lighting with brightness and contrast |
| A score that sits high on an empty bed | Crop out whatever the model is reacting to, such as cables or a cluttered background |
| The same failure alerting again and again | Raise the cooldown |
| A busy processor on a shared host | Lower the camera's detection rate |

[Troubleshooting](troubleshooting.md#detection-and-alerts) covers alerts that never arrive.
