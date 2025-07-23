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
        if len(new_name) > 60:
            new_name = f'{new_name[:57]}...'
        self._track_lbl.text = new_name

    @property
    def media_title(self):
        return self._media_lbl.text

    @media_title.setter
    def media_title(self, new_title):
        self._media_lbl.text = new_title

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

        # terminalio.FONT.get_bounding_box() returns (6, 12)
        # so for scale 2 that means each glyph is 12 x 24
        lines = {
            0: (ax, ay - 36),
            1: (ax, ay - 12),
            2: (ax, ay + 12),
            3: (ax, ay + 36),
        }

        self._artist_lbl = label.Label(terminalio.FONT, text='Artist Name', scale=2)
        self._artist_lbl.anchor_point = (0.5, 0.5)
        self._artist_lbl.anchored_position = lines[2]

        self._album_lbl = label.Label(terminalio.FONT, text='Album Name', scale=2)
        self._album_lbl.anchor_point = (0.5, 0.5)
        self._album_lbl.anchored_position = lines[1]

        self._track_lbl = label.Label(terminalio.FONT, text='Track Name', scale=2)
        self._track_lbl.anchor_point = (0.5, 0.5)
        self._track_lbl.anchored_position = lines[0]

        self._media_lbl = label.Label(terminalio.FONT, text='Media Title', scale=2)
        self._media_lbl.anchor_point = (0.5, 0.5)
        self._media_lbl.anchored_position = lines[3]

        self._prev_indicator = label.Label(terminalio.FONT, text='', scale=4)
        self._prev_indicator.anchor_point = (0.0, 0.5)
        self._prev_indicator.anchored_position = (0, ay)

        self._next_indicator = label.Label(terminalio.FONT, text='', scale=4)
        self._next_indicator.anchor_point = (1.0, 0.5)
        self._next_indicator.anchored_position = (self.width, ay)

        self.append(self._tg)
        self.append(self._artist_lbl)
        self.append(self._album_lbl)
        self.append(self._track_lbl)
        self.append(self._media_lbl)
        self.append(self._prev_indicator)
        self.append(self._next_indicator)

    def show_icon(self, name):
        if name == 'prev':
            self._prev_indicator.text = '<<'
        elif name == 'next':
            self._next_indicator.text = '>>'

    def hide_icon(self, name):
        if name == 'prev':
            self._prev_indicator.text = ''
        elif name == 'next':
            self._next_indicator.text = ''
