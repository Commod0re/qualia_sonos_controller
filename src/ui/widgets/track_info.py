import displayio
import terminalio
from adafruit_display_text import label
from adafruit_displayio_layout.widgets.widget import Widget


class TrackInfo(Widget):
    @property
    def artist_name(self):
        return self._artist_lbl.text

    @artist_name.setter
    def artist_name(self, new_name):
        self._artist_lbl.text = new_name

    @property
    def album_name(self):
        return self._album_lbl.text

    @album_name.setter
    def album_name(self, new_name):
        self._album_lbl.text = new_name

    @property
    def track_name(self):
        return self._track_lbl.text

    @track_name.setter
    def track_name(self, new_name):
        self._track_lbl.text = new_name

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._palette = displayio.Palette(2)
        self._palette[0] = 0x0
        self._palette[1] = 0xffffff

        self._bg = displayio.Bitmap(self.width, self.height, 8)
        self._bg.fill(0)
        self._tg = displayio.TileGrid(
            self._bg, pixel_shader=self._palette, x=0, y=0
        )

        ax = self.width // 2
        ay = self.height // 2

        self._artist_lbl = label.Label(terminalio.FONT, text='Artist Name', scale=2)
        self._artist_lbl.anchor_point = (0.5, 0.5)
        self._artist_lbl.anchored_position = (ax, ay - 24)

        self._album_lbl = label.Label(terminalio.FONT, text='Album Name', scale=2)
        self._album_lbl.anchor_point = (0.5, 0.5)
        self._album_lbl.anchored_position = (ax, ay)

        self._track_lbl = label.Label(terminalio.FONT, text='Track Name', scale=2)
        self._track_lbl.anchor_point = (0.5, 0.5)
        self._track_lbl.anchored_position = (ax, ay + 24)

        self.append(self._tg)
        self.append(self._artist_lbl)
        self.append(self._album_lbl)
        self.append(self._track_lbl)
