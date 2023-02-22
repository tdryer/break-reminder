import argparse
import functools
import logging
import sys

import gi

gi.require_version("Notify", "0.7")
gi.require_version("GnomeDesktop", "3.0")
from gi.repository import GLib, GnomeDesktop, Notify

LOGGER = logging.getLogger(__name__)


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
    _ACTION_POSTPONE_BREAK = "POSTPONE_BREAK"

    def __init__(
        self,
        idle_monitor,
        notification,
        break_duration_ms,
        work_duration_ms,
        postpone_duration_ms,
        idle_timeout_ms,
    ):
        # Assume not idle on start
        self._is_idle = False
        self._work_timer = Timer(work_duration_ms, self._on_work_timer_expired)
        self._break_timer = Timer(break_duration_ms, self._on_break_timer_expired)

        notification.add_action(
            self._ACTION_POSTPONE_BREAK,
            "Postpone",
            self._on_postpone_break,
            postpone_duration_ms,
        )
        self._notification = notification

        self._work_timer.start()
        idle_monitor.add_idle_watch(idle_timeout_ms, self._on_idle_start)

    @callback
    def _on_work_timer_expired(self):
        """Callback when work timer expires."""
        LOGGER.info("Work timer expired")
        self._notification.show()
        self._break_timer.start(reset=True)

    @callback
    def _on_break_timer_expired(self):
        """Callback when break timer expires."""
        LOGGER.info("Break timer expired")
        self._notification.close()
        # Only start timer when active
        if not self._is_idle:
            self._work_timer.start(reset=True)

    @callback
    def _on_postpone_break(self, _notification, action, postpone_duration_ms):
        """Callback when break is postponed."""
        assert action == self._ACTION_POSTPONE_BREAK
        LOGGER.info("Postpone break")
        self._break_timer.stop()
        self._notification.close()
        GLib.timeout_add(postpone_duration_ms, self._on_work_timer_expired)

    @callback
    def _on_idle_start(self, idle_monitor, _watch_id):
        """Callback when idle is started."""
        LOGGER.info("Idle start")
        self._is_idle = True
        # Do not count idle time towards the next break
        if self._work_timer.is_running:
            self._work_timer.stop()
        idle_timestamp = get_timestamp_ms()
        idle_monitor.add_user_active_watch(self._on_idle_end, idle_timestamp)

    @callback
    def _on_idle_end(self, _idle_monitor, _watch_id, idle_timestamp):
        """Callback when idle is ended."""
        elapsed_ms = get_timestamp_ms() - idle_timestamp
        LOGGER.info("Idle end: %s seconds elapsed", elapsed_ms // 1000)
        self._is_idle = False
        # If not in a break, start the timer for the next break again,
        # resetting it if idle for longer than the break interval.
        if not self._break_timer.is_running:
            was_long_idle = elapsed_ms > self._break_timer.interval_ms
            if was_long_idle:
                LOGGER.info("Reset break timer")
            self._work_timer.start(reset=was_long_idle)


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

    notification = Notify.Notification.new("Break Time")
    notification.set_urgency(Notify.Urgency.CRITICAL)

    idle_monitor = GnomeDesktop.IdleMonitor()
    if not idle_monitor.init():
        sys.exit("Failed to initialize idle monitor")

    BreakReminder(
        idle_monitor,
        notification,
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


if __name__ == "__main__":
    main()
