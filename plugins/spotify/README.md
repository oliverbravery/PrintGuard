# Spotify

Puts the cover of whatever is playing behind the dashboard, with the track and its playback controls in a row under your monitors. Pair it with the Glass theme and the dashboard frosts over the art.

![The dashboard with a cover behind the glass](shots/dashboard.jpg)

You sign in to your own Spotify account through PrintGuard, which holds the tokens for the plugin. It reaches api.spotify.com for the player and i.scdn.co for covers, and nowhere else. Playback control needs Spotify Premium, since the API refuses it on free accounts. It needs PrintGuard 3.0.0 or newer.
