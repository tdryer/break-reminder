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
        self._remaining_ms = 0
        self._callback()
        return False


class BreakReminder:
    _ACTION_POSTPONE_BREAK = "POSTPONE_BREAK"

    def __init__(
        self,
        idle_monitor,
        break_interval_ms,
        break_duration_ms,
        break_postpone_seconds,
        idle_timeout_ms,
    ):
        self._idle_monitor = idle_monitor
        self._break_postpone_ms = break_postpone_seconds
        self._is_idle = False  # Assume not idle on start
        self._start_break_timer = Timer(
            break_interval_ms - break_duration_ms, self._on_start_break
        )  # Timer for start of break
        self._end_break_timer = Timer(
            break_duration_ms, self._on_finish_break
        )  # Timer for end of break

        self._notification = Notify.Notification.new("Break Time")
        self._notification.set_urgency(Notify.Urgency.CRITICAL)
        self._notification.add_action(
            self._ACTION_POSTPONE_BREAK, "Postpone", self._on_postpone_break
        )

        self._start_break_timer.start()
        self._idle_monitor.add_idle_watch(idle_timeout_ms, self._on_idle_start)

    @callback
    def _on_start_break(self):
        """Callback when break is started."""
        LOGGER.info("Start break")
        self._notification.show()
        self._end_break_timer.start(reset=True)

    @callback
    def _on_finish_break(self):
        """Callback when break is finished."""
        LOGGER.info("Finish break")
        self._notification.close()
        if self._is_idle:
            # Ensure timer is reset before it is started again
            self._start_break_timer.start(reset=True)
            self._start_break_timer.stop()
        else:
            # Wait until active again to start break timer
            self._start_break_timer.start(reset=True)

    @callback
    def _on_postpone_break(self, _notification, action):
        """Callback when break is postponed."""
        assert action == self._ACTION_POSTPONE_BREAK
        LOGGER.info("Postpone break")
        self._end_break_timer.stop()
        self._notification.close()
        GLib.timeout_add(self._break_postpone_ms, self._on_start_break)

    @callback
    def _on_idle_start(self, _monitor, _watch_id):
        """Callback when idle is started."""
        LOGGER.info("Idle start")
        self._is_idle = True
        # Do not count idle time towards the next break
        if self._start_break_timer.is_running:
            self._start_break_timer.stop()
        idle_timestamp = get_timestamp_ms()
        self._idle_monitor.add_user_active_watch(self._on_idle_end, idle_timestamp)

    @callback
    def _on_idle_end(self, _monitor, _watch_id, idle_timestamp):
        """Callback when idle is finished."""
        elapsed_ms = get_timestamp_ms() - idle_timestamp
        LOGGER.info("Idle end: %s seconds elapsed", elapsed_ms // 1000)
        self._is_idle = False
        # If not in a break, start the timer for the next break again,
        # resetting it if idle for longer than the break interval.
        if not self._end_break_timer.is_running:
            was_long_idle = elapsed_ms > self._end_break_timer.interval_ms
            if was_long_idle:
                LOGGER.info("Reset break timer")
            self._start_break_timer.start(reset=was_long_idle)


def main():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--break-interval-seconds",
        type=int,
        default=60 * 60,
        help="Break interval in seconds",
    )
    parser.add_argument(
        "--break-duration-seconds",
        type=int,
        default=5 * 60,
        help="Break duration in seconds",
    )
    parser.add_argument(
        "--break-postpone-seconds",
        type=int,
        default=5 * 60,
        help="Duration break can be postponed in seconds",
    )
    parser.add_argument(
        "--idle-timeout-seconds",
        type=int,
        default=2 * 60,
        help="Idle timeout in seconds",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
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

    BreakReminder(
        idle_monitor,
        args.break_interval_seconds * 1000,
        args.break_duration_seconds * 1000,
        args.break_postpone_seconds * 1000,
        args.idle_timeout_seconds * 1000,
    )

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        LOGGER.info("Caught SIGINT")


if __name__ == "__main__":
    main()
