import datetime
import logging
import sys

import gi

gi.require_version("Notify", "0.7")
gi.require_version("GnomeDesktop", "3.0")
from gi.repository import Notify, GnomeDesktop, GLib

LOGGER = logging.getLogger(__name__)


# TODO: use these
BREAK_INTERVAL = datetime.timedelta(hours=1)
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
        self.reset()
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


def main():
    logging.basicConfig(
        format="%(asctime)s %(levelname)-8s %(message)s", level=logging.INFO
    )

    if not Notify.init("Break Reminder"):
        sys.exit("Failed to initialize desktop notifications")

    # TODO:
    def on_finish_break():
        logging.info("Finished break")

    def on_start_break():
        logging.info("Showing notification")
        # TODO: Should probably replace previous notification
        # TODO: Need to track length of break so idle time does not delay next break
        notification = Notify.Notification.new("Break Time")
        notification.set_urgency(Notify.Urgency.CRITICAL)
        notification.show()

    timer = Timer(5000, on_start_break)

    # stops working if idle_monitor is GC'd
    idle_monitor = GnomeDesktop.IdleMonitor()
    assert idle_monitor.init()

    def active_cb(monitor, watch_id, idle_timestamp):
        # TODO: Reset timer instead if too much time elapsed
        timer.resume()
        elapsed = GLib.get_monotonic_time() - idle_timestamp
        LOGGER.info("User is active again after %s", elapsed // 1000)

    def idle_cb(monitor, watch_id):
        LOGGER.info("User is idle")
        timer.pause()
        idle_timestamp = GLib.get_monotonic_time()
        user_active_watch_id = idle_monitor.add_user_active_watch(
            active_cb, idle_timestamp
        )

    idle_watch_id = idle_monitor.add_idle_watch(1000, idle_cb)

    try:
        GLib.MainLoop().run()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
