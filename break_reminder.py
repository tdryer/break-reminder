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


class Timer:
    def __init__(self, interval_ms, callback_):
        self._interval_ms = interval_ms
        self._callback = callback_
        self._start_timestamp_ms = None
        self._remaining_ms = None
        self._source = None
        self.reset()

    @callback
    def _on_timeout_expiry(self):
        LOGGER.info("Timer expired")
        self._callback()
        return False

    def _remove_source(self):
        if self._source is not None:
            GLib.Source.remove(self._source)
            self._source = None

    def _get_timestamp_ms(self):
        return GLib.get_monotonic_time() // 1000

    def pause(self):
        self._remove_source()
        self._remaining_ms = max(
            self._interval_ms - (self._get_timestamp_ms() - self._start_timestamp_ms), 0
        )
        LOGGER.info("Timer paused: %s seconds remaining", self._remaining_ms // 1000)
        self._start_timestamp_ms = self._get_timestamp_ms()

    def resume(self):
        self._source = GLib.timeout_add(self._remaining_ms, self._on_timeout_expiry)
        LOGGER.info("Timer resumed: %s seconds remaining", self._remaining_ms // 1000)
        self._remaining_ms = None

    def reset(self):
        self._remove_source()
        self._start_timestamp_ms = self._get_timestamp_ms()
        self._source = GLib.timeout_add(self._interval_ms, self._on_timeout_expiry)
        self._remaining_ms = None
        LOGGER.info("Timer reset")


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
        self._break_interval_ms = break_interval_ms
        self._break_duration_ms = break_duration_ms
        self._break_postpone_ms = break_postpone_seconds
        self._idle_timeout_ms = idle_timeout_ms
        self._is_idle = False  # Assume not idle on start
        # TODO: combine timers?
        self._start_break_timer = None  # Timer for start of break
        self._end_break_timer = None  # Timer for end of break

        self._notification = Notify.Notification.new("Break Time")
        self._notification.set_urgency(Notify.Urgency.CRITICAL)
        self._notification.add_action(
            self._ACTION_POSTPONE_BREAK, "Postpone", self._on_postpone_break
        )

    def start(self):
        self._begin_start_break_timer()
        self._idle_monitor.add_idle_watch(self._idle_timeout_ms, self._on_idle_start)

    def _begin_start_break_timer(self):
        """Start timer for the next break."""
        interval_ms = self._break_interval_ms - self._break_duration_ms
        assert self._start_break_timer is None
        self._start_break_timer = Timer(interval_ms, self._on_start_break)

    @callback
    def _on_start_break(self):
        """Callback when break is started."""
        logging.info("Start break")
        self._notification.show()
        self._start_break_timer = None
        assert self._end_break_timer is None
        self._end_break_timer = Timer(self._break_duration_ms, self._on_finish_break)

    @callback
    def _on_finish_break(self):
        """Callback when break is finished."""
        logging.info("Finish break")
        self._notification.close()
        self._end_break_timer = None
        self._begin_start_break_timer()
        if self._is_idle:
            self._start_break_timer.pause()

    @callback
    def _on_postpone_break(self, _notification, action):
        """Callback when break is postponed."""
        assert action == self._ACTION_POSTPONE_BREAK
        logging.info("Postpone break")
        assert self._end_break_timer
        # TODO: Add cancel method to timer?
        self._end_break_timer.pause()
        self._end_break_timer = None
        self._notification.close()
        GLib.timeout_add(
            self._break_postpone_ms,
            self._on_start_break,
        )

    @callback
    def _on_idle_start(self, _monitor, _watch_id):
        """Callback when idle is started."""
        LOGGER.info("Idle start")
        self._is_idle = True
        if self._start_break_timer is not None:
            self._start_break_timer.pause()
        idle_timestamp = GLib.get_monotonic_time()
        self._idle_monitor.add_user_active_watch(self._on_idle_end, idle_timestamp)

    @callback
    def _on_idle_end(self, _monitor, _watch_id, idle_timestamp):
        """Callback when idle is finished."""
        elapsed_ms = (GLib.get_monotonic_time() - idle_timestamp) // 1000
        LOGGER.info("Idle end: %s seconds elapsed", elapsed_ms // 1000)
        self._is_idle = False
        if self._start_break_timer is not None:
            if elapsed_ms > self._break_duration_ms:
                self._start_break_timer.reset()
            else:
                self._start_break_timer.resume()


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
    ).start()

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        LOGGER.info("Caught SIGINT")


if __name__ == "__main__":
    main()
