import datetime
import logging
import sys

import gi

gi.require_version("Notify", "0.7")
gi.require_version("GnomeDesktop", "3.0")
from gi.repository import Notify, GnomeDesktop, GLib

LOGGER = logging.getLogger(__name__)


BREAK_INTERVAL = datetime.timedelta(minutes=60)
BREAK_DURATION = datetime.timedelta(minutes=5)
IDLE_TIMEOUT = datetime.timedelta(minutes=1)


class Timer:
    def __init__(self, interval, callback):
        self._interval = interval
        self._callback = callback
        self._start_time = None
        self._elapsed = None
        self._source = None
        self.reset()

    def _on_timeout_expiry(self, *args):
        try:
            self._callback()
        except:
            LOGGER.exception("Exception in timer callback")
        return False

    def _remove_source(self):
        if self._source is not None:
            GLib.Source.remove(self._source)
            self._source = None

    def pause(self):
        LOGGER.info("Pausing timer")
        self._remove_source()
        self._elapsed = GLib.get_monotonic_time() - self._start_time

    def resume(self):
        LOGGER.info("Resuming timer")
        remaining = max(self._interval - self._elapsed, 0)
        self._start_time = GLib.get_monotonic_time()
        self._source = GLib.timeout_add(remaining, self._on_timeout_expiry)

    def reset(self):
        LOGGER.info("Resetting timer")
        self._remove_source()
        self._start_time = GLib.get_monotonic_time()
        self._elapsed = 0
        self._source = GLib.timeout_add(self._interval, self._on_timeout_expiry)


class BreakReminder:
    def __init__(self, idle_monitor):
        self._idle_monitor = idle_monitor
        self._timer = None

    def start(self):
        self._start_break_timer()
        idle_watch_id = self._idle_monitor.add_idle_watch(
            IDLE_TIMEOUT / datetime.timedelta(milliseconds=1), self._on_idle_start
        )

    def _start_break_timer(self):
        """Start timer for the next break."""
        interval_ms = (BREAK_INTERVAL - BREAK_DURATION) / datetime.timedelta(
            milliseconds=1
        )
        self._timer = Timer(interval_ms, self._on_start_break)

    def _on_start_break(self):
        """Callback when break is started."""
        logging.info("Start break")
        # TODO: Need to track length of break so idle time does not delay next break
        notification = Notify.Notification.new("Break Time")
        notification.set_urgency(Notify.Urgency.CRITICAL)
        notification.show()

        GLib.timeout_add(
            BREAK_DURATION / datetime.timedelta(milliseconds=1),
            self._on_finish_break,
            notification,
        )

    def _on_finish_break(self, notification):
        """Callback when break is finished."""
        logging.info("Finish break")
        notification.close()
        # TODO: Pause the timer if currently idle
        self._start_break_timer()

    def _on_idle_start(self, monitor, watch_id):
        """Callback when idle is started."""
        LOGGER.info("Idle start")
        # self._timer.pause()
        idle_timestamp = GLib.get_monotonic_time()
        user_active_watch_id = self._idle_monitor.add_user_active_watch(
            self._on_idle_end, idle_timestamp
        )

    def _on_idle_end(self, monitor, watch_id, idle_timestamp):
        """Callback when idle is finished."""
        LOGGER.info("Idle end")
        # TODO: Reset timer instead if too much time elapsed
        # self._timer.resume()
        elapsed = GLib.get_monotonic_time() - idle_timestamp
        # LOGGER.info("User is active again after %s", elapsed // 1000)


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
        pass


if __name__ == "__main__":
    main()
