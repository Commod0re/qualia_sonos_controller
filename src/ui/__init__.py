import asyncio
import board
import busio
import displayio
import dotclockframebuffer
import wifi
from framebufferio import FramebufferDisplay
from adafruit_displayio_layout.layouts.linear_layout import LinearLayout

from .widgets.placeholder import Placeholder
from .widgets.statusbar import StatusBar

displayio.release_displays()
tft_pins = dict(board.TFT_PINS)
tft_timings = {
    "frequency": 16000000,
    "width": 720,
    "height": 720,
    "hsync_pulse_width": 2,
    "hsync_front_porch": 46,
    "hsync_back_porch": 44,
    "vsync_pulse_width": 2,
    "vsync_front_porch": 16,
    "vsync_back_porch": 18,
    "hsync_idle_low": False,
    "vsync_idle_low": False,
    "de_idle_high": False,
    "pclk_active_high": False,
    "pclk_idle_high": False,
}
init_sequence_tl040hds20 = bytes()

board.I2C().deinit()
i2c = busio.I2C(board.SCL, board.SDA)
tft_io_expander = dict(board.TFT_IO_EXPANDER)
# tft_io_expander['i2c_address'] = 0x38 # uncomment for rev B
dotclockframebuffer.ioexpander_send_init_sequence(i2c, init_sequence_tl040hds20, **tft_io_expander)
# i2c.deinit()


fb = dotclockframebuffer.DotClockFramebuffer(**tft_pins, **tft_timings)
display = FramebufferDisplay(fb, auto_refresh=False)

# Make the display context
main_group = displayio.Group()
display.root_group = main_group



layout = LinearLayout(0, 0)

# set up and add the status bar to the ui
status_bar = StatusBar(width=720, height=24)
layout.add_content(status_bar)

album_art_placeholder = Placeholder('album_art', width=400, height=400)
layout.add_content(album_art_placeholder)

play_progress_placeholder = Placeholder('play_progress', height=20, width=600)
layout.add_content(play_progress_placeholder)

track_info_placeholder = Placeholder('track_info', height=72, width=500)
layout.add_content(track_info_placeholder)

playlist_preview_placeholder = Placeholder('play_queue_preview', height=32*5, width=720)
layout.add_content(playlist_preview_placeholder)

# TODO: whatever goes next

main_group.append(layout)


def refresh():
    display.refresh()
