import bitmaptools
import displayio
import terminalio
from adafruit_display_text import label
from adafruit_displayio_layout.widgets.widget import Widget


class StatusBar(Widget):
    @property
    def ip(self):
        return self._ip.text

    @ip.setter
    def ip(self, ip):
        self._ip.text = ip

    @property
    def sonos(self):
        return self._sonos.text

    @sonos.setter
    def sonos(self, ip):
        self._sonos.text = ip

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._palette = displayio.Palette(3)
        self._palette[0] = 0x888888
        self._palette[1] = 0xffffff
        self._palette[2] = 0x0

        # statusbar background
        self._bg = displayio.Bitmap(self.width, self.height, 8)
        self._bg.fill(0)
        bitmaptools.draw_line(
            self._bg,
            x1=0, x2=self.width,
            y1=self.height, y2=self.height,
            value=1
        )
        self._tilegrid = displayio.TileGrid(
            self._bg, pixel_shader=self._palette, x=0, y=0
        )

        # labels
        self._ip = label.Label(terminalio.FONT, text='???.???.???.???', scale=2, color=self._palette[2])
        self._ip.anchor_point = (0.0, 0.0)
        self._ip.anchored_position = (2, 0)

        self._sonos = label.Label(terminalio.FONT, text='?', scale=2, color=self._palette[2])
        self._sonos.anchor_point = (1.0, 0.0)
        self._sonos.anchored_position = (self.width - 2, 0)

        self.append(self._tilegrid)
        self.append(self._ip)
        self.append(self._sonos)
