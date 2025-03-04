import bitmaptools
import displayio
from adafruit_displayio_layout.widgets.widget import Widget


class Slider(Widget):
    @property
    def background_color(self):
        return self._palette[1]

    @background_color.setter
    def background_color(self, new_color):
        self._palette[1] = new_color

    @property
    def border_color(self):
        return self._palette[2]

    @border_color.setter
    def border_color(self, new_color):
        self._palette[2] = new_color

    @property
    def color(self):
        return self._palette[3]

    @color.setter
    def color(self, new_color):
        self._palette[3] = new_color

    @property
    def position(self):
        return self._pos

    @position.setter
    def position(self, new_pos):
        self._set_position(new_pos)

    def __init__(self, background_color=0x0, border_color=0xffffff, color=0x00ff00, starting_pos=0.5, orientation='vertical', **kwargs):
        super().__init__(**kwargs)

        self._palette = displayio.Palette(4)
        self._palette.make_transparent(0)
        self.background_color = background_color
        self.border_color = border_color
        self.color = color

        self._bg = displayio.Bitmap(self.width, self.height, 8)
        self._fg = displayio.Bitmap(self.width - 2, self.height - 2, 8)
        self._pos = 0.0

        # draw the border
        self._bg.fill(2)
        bitmaptools.fill_region(
            self._bg,
            x1=1, y1=1,
            x2=self.width - 1, y2=self.height - 1,
            value=1
        )

        self._bg_tilegrid = displayio.TileGrid(
            self._bg, pixel_shader=self._palette, x=0, y=0
        )
        self._fg_tilegrid = displayio.TileGrid(
            self._fg, pixel_shader=self._palette, x=1, y=1
        )

        self.append(self._bg_tilegrid)
        self.append(self._fg_tilegrid)

        self._orientation = orientation
        self.position = starting_pos

    def _set_position(self, new_pos):
        if new_pos < self._pos:
            self._fg.fill(0)
        bar_width = self._fg.width
        bar_height = self._fg.height
        if self._orientation == 'vertical':
            y1 = int((1.0 - new_pos) * bar_height)
            x2 = bar_width
        else:
            y1 = 0
            x2 = int(new_pos * bar_width)
        bitmaptools.fill_region(
            self._fg,
            x1=0, y1=y1,
            x2=x2, y2=bar_height,
            value=3
        )
        self._pos = new_pos
