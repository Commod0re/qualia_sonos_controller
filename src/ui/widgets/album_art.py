import displayio
import jpegio
import math
from adafruit_displayio_layout.widgets.widget import Widget


class AlbumArt(Widget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._decoder = jpegio.JpegDecoder()
        self._cc = displayio.ColorConverter(input_colorspace=displayio.Colorspace.RGB565_SWAPPED)
        self._bg = displayio.Bitmap(self.height, self.height, 65535)
        self._tg = displayio.TileGrid(self._bg, pixel_shader=self._cc, x=(self.width-self.height)//2, y=0)
        self.append(self._tg)

        self.clear()

    def clear(self):
        self.show('/assets/placeholder.jpeg')

    def show(self, buf):
        try:
            width, height = self._decoder.open(buf)
        except RuntimeError as e:
            # progressive jpeg :(
            print(e)
            self.clear()
            return

        x1, y1 = 0, 0
        # jpegio can't scale UP
        # so just center smaller images
        if width < self.height:
            self._bg.fill(0)
            x1 = self.height - width
            y1 = self.height - height

        self._decoder.decode(self._bg, x1=x1, y1=y1)
