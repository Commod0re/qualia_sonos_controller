import terminalio
from adafruit_display_text import label
from .slider import Slider


def time_to_seconds(timestr):
    h, m, s = (int(tp) for tp in timestr.split(':'))
    return (3600 * h) + (60 * m) + s


def seconds_to_time(seconds):
    h = seconds // 3600
    seconds -= (3600 * h)
    m = seconds // 60
    seconds -= (60 * m)
    if h:
        return f'{h:02d}:{m:02d}:{seconds:02d}'
    return f'{m:02d}:{seconds:02d}'


class PlayProgress(Slider):
    @property
    def track_duration(self):
        return seconds_to_time(self._duration_seconds)

    @track_duration.setter
    def track_duration(self, new_duration):
        self._duration_label.text = new_duration
        self._duration_seconds = time_to_seconds(new_duration)

    @property
    def play_position(self):
        return seconds_to_time(self._position_seconds)

    @play_position.setter
    def play_position(self, new_position):
        self._pos_label.text = new_position
        self._position_seconds = time_to_seconds(new_position)
        if self._duration_seconds:
            self.position = self._position_seconds / self._duration_seconds
        else:
            self.position = 0.0

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='horizontal', **kwargs)

        self._duration_seconds = 0
        self._position_seconds = 0

        self._pos_label = label.Label(terminalio.FONT, text='00:00', scale=2)
        self._pos_label.anchor_point = (0.0, 0.5)
        self._pos_label.anchored_position = (3, self.height // 2)
        self._pos_label._palette.make_opaque(0)

        self._duration_label = label.Label(terminalio.FONT, text='00:00', scale=2)
        self._duration_label.anchor_point = (1.0, 0.5)
        self._duration_label.anchored_position = (self.width - 3, self.height // 2)
        self._duration_label._palette.make_opaque(0)

        self.append(self._pos_label)
        self.append(self._duration_label)
