from datetime import timedelta
import logging
import sys

import gi

gi.require_version("Notify", "0.7")
gi.require_version("GnomeDesktop", "3.0")
from gi.repository import Notify, GnomeDesktop, GLib

LOGGER = logging.getLogger(__name__)


# BREAK_INTERVAL = timedelta(minutes=60)
# BREAK_DURATION = timedelta(minutes=5)
# IDLE_TIMEOUT = timedelta(minutes=1)
BREAK_INTERVAL = timedelta(seconds=10)
BREAK_DURATION = timedelta(seconds=5)
IDLE_TIMEOUT = timedelta(seconds=1)


class Timer:
    def __init__(self, interval_ms, callback):
        self._interval_ms = interval_ms
        self._callback = callback
        self._start_timestamp_ms = None
        self._elapsed_ms = None
        self._source = None
        self.reset()

    def _on_timeout_expiry(self):
        try:
            self._callback()
        except:
            LOGGER.exception("Exception in timer callback")
        return False

    def _remove_source(self):
        if self._source is not None:
            GLib.Source.remove(self._source)
            self._source = None

    def _get_timestamp_ms(self):
        return GLib.get_monotonic_time() // 1000

    def pause(self):
        self._remove_source()
        # TODO: Replace with remaining time?
        self._elapsed_ms = self._get_timestamp_ms() - self._start_timestamp_ms
        LOGGER.info("Pausing timer: %s seconds elapsed", self._elapsed_ms // 1000)

    def resume(self):
        remaining_ms = max(self._interval_ms - self._elapsed_ms, 0)
        LOGGER.info("Resuming timer: %s seconds remaining", remaining_ms // 1000)
        self._start_timestamp_ms = self._get_timestamp_ms()
        self._source = GLib.timeout_add(remaining_ms, self._on_timeout_expiry)

    def reset(self):
        LOGGER.info("Resetting timer")
        self._remove_source()
        self._start_timestamp_ms = self._get_timestamp_ms()
        self._elapsed_ms = 0
        self._source = GLib.timeout_add(self._interval_ms, self._on_timeout_expiry)


class BreakReminder:
    def __init__(self, idle_monitor):
        self._idle_monitor = idle_monitor
        self._is_idle = False  # Assume not idle on start
        self._timer = None

    def start(self):
        self._start_break_timer()
        self._idle_monitor.add_idle_watch(
            IDLE_TIMEOUT / timedelta(milliseconds=1), self._on_idle_start
        )

    def _start_break_timer(self):
        """Start timer for the next break."""
        interval_ms = (BREAK_INTERVAL - BREAK_DURATION) / timedelta(milliseconds=1)
        assert self._timer is None
        self._timer = Timer(interval_ms, self._on_start_break)

    def _on_start_break(self):
        """Callback when break is started."""
        logging.info("Start break")
        notification = Notify.Notification.new("Break Time")
        notification.set_urgency(Notify.Urgency.CRITICAL)
        notification.show()
        self._timer = None
        GLib.timeout_add(
            BREAK_DURATION / timedelta(milliseconds=1),
            self._on_finish_break,
            notification,
        )

    def _on_finish_break(self, notification):
        """Callback when break is finished."""
        logging.info("Finish break")
        notification.close()
        self._start_break_timer()
        if self._is_idle:
            self._timer.pause()

    def _on_idle_start(self, _monitor, _watch_id):
        """Callback when idle is started."""
        LOGGER.info("Idle start")
        self._is_idle = True
        if self._timer is not None:
            self._timer.pause()
        idle_timestamp = GLib.get_monotonic_time()
        self._idle_monitor.add_user_active_watch(self._on_idle_end, idle_timestamp)

    def _on_idle_end(self, _monitor, _watch_id, idle_timestamp):
        """Callback when idle is finished."""
        elapsed = timedelta(microseconds=GLib.get_monotonic_time() - idle_timestamp)
        LOGGER.info("Idle end: %s seconds elapsed", int(elapsed.total_seconds()))
        self._is_idle = False
        if self._timer is not None:
            if elapsed > BREAK_DURATION:
                self._timer.reset()
            else:
                self._timer.resume()
        else:
            # TODO: Only do this if we're not on break still?
            self._start_break_timer()


def main():
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s", level=logging.INFO
    )

    if not Notify.init("Break Reminder"):
        sys.exit("Failed to initialize notifier")

    idle_monitor = GnomeDesktop.IdleMonitor()
    if not idle_monitor.init():
        sys.exit("Failed to initialize idle monitor")

    BreakReminder(idle_monitor).start()

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        LOGGER.info("Caught SIGINT")


if __name__ == "__main__":
    main()
