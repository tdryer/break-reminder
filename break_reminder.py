import argparse
import functools
import logging
import sys

import gi

gi.require_version("Notify", "0.7")
gi.require_version("GnomeDesktop", "3.0")
from gi.repository import GLib, GnomeDesktop, Notify

LOGGER = logging.getLogger(__name__)

NOTIFY_CLOSED_REASON_DISMISSED = 2


def callback(func):
    """Wrap callback to exit if there is an unhandled exception."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            func(*args, **kwargs)
        except Exception:
            LOGGER.exception("Callback raised unhandled exception")
            sys.exit(1)

    return wrapper


def get_timestamp_ms():
    """Get monotonic ms timestamp."""
    return GLib.get_monotonic_time() // 1000


class Timer:
    """GLib-based timer that can be stopped and restarted."""

    def __init__(self, interval_ms, callback_):
        self._interval_ms = interval_ms
        self._callback = callback_
        self._start_timestamp_ms = None
        self._remaining_ms = interval_ms
        self._source = None

    @property
    def is_running(self):
        """Whether the timer is running."""
        return self._source is not None

    @property
    def interval_ms(self):
        """Timer interval in ms."""
        return self._interval_ms

    def start(self, reset=False):
        """Start (and optionally reset) timer."""
        assert not self.is_running
        if reset:
            self._remaining_ms = self._interval_ms
        self._start_timestamp_ms = get_timestamp_ms()
        self._source = GLib.timeout_add(self._remaining_ms, self._on_timeout_expiry)

    def stop(self):
        """Stop timer."""
        assert self.is_running
        GLib.Source.remove(self._source)
        self._source = None
        elapsed_ms = get_timestamp_ms() - self._start_timestamp_ms
        self._remaining_ms = max(self._remaining_ms - elapsed_ms, 0)

    @callback
    def _on_timeout_expiry(self):
        self._source = None
        self._remaining_ms = self._interval_ms
        self._callback()
        return False


class BreakReminder:
    def __init__(
        self,
        idle_monitor,
        break_duration_ms,
        work_duration_ms,
        postpone_duration_ms,
        idle_timeout_ms,
    ):
        self._work_timer = Timer(work_duration_ms, self._on_work_timer_expired)
        self._break_timer = Timer(
            break_duration_ms - idle_timeout_ms, self._on_break_timer_expired
        )
        self._postpone_timer = Timer(postpone_duration_ms, self._on_postpone_expired)

        notification = Notify.Notification.new("Break Time")
        # Keep notification on screen until dismissed.
        notification.set_urgency(Notify.Urgency.CRITICAL)
        # Do not automatically close notification after action is invoked since
        # this can't be distinguished from the user dismissing the
        # notification.
        notification.set_hint("resident", GLib.Variant.new_boolean(True))
        notification.connect("closed", self._on_notification_closed)
        notification.add_action("postpone", "Postpone", self._on_notification_postponed)
        self._notification = notification

        self._work_timer.start()
        idle_monitor.add_idle_watch(idle_timeout_ms, self._on_idle_start)

    def close_notification(self):
        """Close notification."""
        self._notification.close()

    @callback
    def _on_work_timer_expired(self):
        """Callback when work timer expires."""
        LOGGER.info("Work timer expired")
        self._notification.show()

    @callback
    def _on_break_timer_expired(self):
        """Callback when break timer expires."""
        LOGGER.info("Break timer expired")
        self._notification.close()
        if self._postpone_timer.is_running:
            LOGGER.info("Postpone timer cancelled")
            self._postpone_timer.stop()

    @callback
    def _on_idle_start(self, idle_monitor, _watch_id):
        """Callback when idle is started."""
        LOGGER.info("Idle start")
        work_timer_was_running = self._work_timer.is_running
        if self._work_timer.is_running:
            self._work_timer.stop()
        self._break_timer.start(reset=True)
        idle_monitor.add_user_active_watch(self._on_idle_end, work_timer_was_running)

    @callback
    def _on_idle_end(self, _idle_monitor, _watch_id, work_timer_was_running):
        """Callback when idle is ended."""
        LOGGER.info("Idle end")
        if self._break_timer.is_running:
            self._break_timer.stop()
            if work_timer_was_running:
                self._work_timer.start()
        else:
            self._work_timer.start(reset=True)

    def _postpone_break(self):
        """Postpone the break notification."""
        LOGGER.info("Starting postpone timer")
        self._postpone_timer.start(reset=True)

    @callback
    def _on_postpone_expired(self):
        LOGGER.info("Postpone timer expired")
        self._notification.show()

    @callback
    def _on_notification_closed(self, notification):
        """Callback when notification is closed."""
        if notification.get_closed_reason() != NOTIFY_CLOSED_REASON_DISMISSED:
            return
        LOGGER.info("Notification dismissed")
        self._postpone_break()

    @callback
    def _on_notification_postponed(self, _notification, _action):
        """Callback when notification is postponed."""
        LOGGER.info("Notification postponed")
        self._notification.close()
        self._postpone_break()


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--break-duration",
        type=int,
        default=5,
        help="Break interval in minutes",
    )
    parser.add_argument(
        "--work-duration",
        type=int,
        default=55,
        help="Work duration in minutes",
    )
    parser.add_argument(
        "--postpone-duration",
        type=int,
        default=5,
        help="Postpone duration in minutes",
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=2,
        help="Idle timeout in minutes",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )
    parser.add_argument(
        "--ms-per-minute",
        type=int,
        default=60_000,
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s",
        level=logging.DEBUG if args.debug else logging.WARNING,
    )

    if not Notify.init("Break Reminder"):
        sys.exit("Failed to initialize notifier")

    idle_monitor = GnomeDesktop.IdleMonitor()
    if not idle_monitor.init():
        sys.exit("Failed to initialize idle monitor")

    break_reminder = BreakReminder(
        idle_monitor,
        args.break_duration * args.ms_per_minute,
        args.work_duration * args.ms_per_minute,
        args.postpone_duration * args.ms_per_minute,
        args.idle_timeout * args.ms_per_minute,
    )
    LOGGER.warning("Started")

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        LOGGER.warning("Caught SIGINT")
        break_reminder.close_notification()


if __name__ == "__main__":
    main()
