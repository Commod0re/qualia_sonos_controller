import asyncio
import board
import busio
import displayio
import dotclockframebuffer
import wifi
from framebufferio import FramebufferDisplay
from adafruit_displayio_layout.layouts.linear_layout import LinearLayout

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
status_bar = StatusBar(x=0, y=0, width=720, height=24)
layout.add_content(status_bar)

# TODO: whatever goes below the status bar

main_group.append(layout)

#########
# testing
#########

async def ip_changed(last_ip):
    while True:
        await asyncio.sleep(1)
        cur_ip = str(wifi.radio.ipv4_address) if wifi.radio.connected else None
        if last_ip != cur_ip:
            return


async def main():
    loop = asyncio.get_event_loop()

    async def _ip():
        status_bar.ip = ip = str(wifi.radio.ipv4_address)
        while True:
            try:
                await asyncio.wait_for(ip_changed(ip), timeout=300)
            except asyncio.TimeoutError:
                # timed out; ip never changed
                continue

            # update display
            ip = str(wifi.radio.ipv4_address)
            status_bar.ip = ip or 'disconnected'

    loop.create_task(_ip())

    while True:
        await asyncio.sleep_ms(1000 // 60)
        display.refresh()


if __name__ == '__main__':
    try:
        asyncio.new_event_loop().run_until_complete(main())
    finally:
        i2c.deinit()
        raise