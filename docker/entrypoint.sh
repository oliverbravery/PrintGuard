#!/bin/bash

export DBUS_SESSION_BUS_ADDRESS=$(dbus-daemon --session --fork --print-address)

gnome-keyring-daemon --start --components=secrets

sleep 2

exec "$@"