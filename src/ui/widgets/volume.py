import terminalio
from adafruit_display_text import label
from .slider import Slider


class Volume(Slider):
    @property
    def volume(self):
        return int(self.position * 100)

    @volume.setter
    def volume(self, new_vol):
        self._vol_label.text = f'{new_vol}'
        self.position = new_vol / 100

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='vertical', **kwargs)

        self._vol_label = label.Label(terminalio.FONT, text='50', scale=2)
        self._vol_label.anchor_point = (0.5, 0.5)
        self._vol_label.anchored_position = (self.width // 2, self.height // 2)
        self._vol_label._palette.make_opaque(0)

        self.append(self._vol_label)
