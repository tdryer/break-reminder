# Break Reminder

A break reminder daemon for GNOME.

* Shows notification when desktop has been active for the work interval.
* Closes notification when desktop has been idle for the break interval.
* Notification action allows hiding the notification for the postpone interval.
* Idle monitor is aware of applications that inhibit idle.

## Install

Run `make install`.

The included systemd unit will automatically run the daemon.

## Uninstall

Run `make uninstall`.

## Usage

See `break-reminder --help`.

## Configure

Command line arguments used by the systemd unit can be configured via the
environment file located in `XDG_CONFIG_HOME`; eg.
`~/.config/break-reminder.env`:

    BREAK_REMINDER_ARGS=--debug

## Known Issues

### Google Chrome

When running under X11, [Google Chrome will reset the idle timer after playing
audio][1], including notification sounds. A workaround for this is to [disable
the X Screen Saver extension][2].

[1]: https://bugs.chromium.org/p/chromium/issues/detail?id=827528
[2]: https://unix.stackexchange.com/a/707430
