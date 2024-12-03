import bitmaptools
import displayio
import terminalio
from adafruit_display_text import label
from adafruit_displayio_layout.widgets.widget import Widget


class Placeholder(Widget):
    def __init__(self, name, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._palette = displayio.Palette(2)
        self._palette.make_transparent(0)
        self._palette[1] = 0xffffff

        self._bg = displayio.Bitmap(self.width, self.height, 8)
        self._bg.fill(1)
        bitmaptools.fill_region(
            self._bg,
            x1=1, y1=1,
            x2=self.width-1, y2=self.height-1,
            value=0
        )

        self._bg_tilegrid = displayio.TileGrid(
            self._bg, pixel_shader=self._palette, x=0, y=0
        )

        self._label = label.Label(terminalio.FONT, text=name, scale=2)
        self._label.anchor_point = (0.5, 0.5)
        self._label.anchored_position = (self.width // 2, self.height // 2)

        self.append(self._bg_tilegrid)
        self.append(self._label)
