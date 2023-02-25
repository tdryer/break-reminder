# Break Reminder

A break reminder daemon for GNOME.

## Install

    make deb
    sudo apt install ./*.deb
    systemctl --user enable break-reminder --now

## Uninstall

    systemctl --user disable break-reminder --now
    sudo apt remove break-reminder

## Configure

Command line arguments used by the systemd unit can be configured via the
environment file located in `XDG_CONFIG_HOME`; eg.
`~/.config/break-reminder.env`:

    BREAK_REMINDER_ARGS=--debug
