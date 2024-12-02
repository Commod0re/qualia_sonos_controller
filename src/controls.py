import asyncio
import board
import digitalio

import adafruit_pca9554
from adafruit_seesaw import seesaw, rotaryio


ANO_BUTTON_MAP = {
    'select': 1,
    'up': 2,
    'left': 3,
    'down': 4,
    'right': 5,
}

async def _scan(bus, addr):
    # scan i2c bus for our device
    while not bus.try_lock():
        await asyncio.sleep(0.1)
    if addr not in bus.scan():
        raise Exception(f'no i2c device found at 0x{addr:02x}')
    bus.unlock()


class AnoRotary:
    @classmethod
    async def new(cls, bus, addr=0x49):
        await _scan(bus, addr)

        # initialize seesaw
        ssw = seesaw.Seesaw(bus, addr=addr)

        # initialize rotary encoder
        encoder = rotaryio.IncrementalEncoder(ssw)

        # instantiate AnoRotary obj
        obj = cls(bus, addr, ssw, encoder)

        # start monitor tasks
        await obj._start_monitor()

        return obj

    def __init__(self, bus, addr, seesaw, encoder):
        self.i2c = bus
        self.addr = addr
        self.seesaw = seesaw
        self.encoder = encoder
        # prepare events
        self.events = {
            f'{name}_{direction}': asyncio.Event()
            for name in ANO_BUTTON_MAP
            for direction in ('press', 'release')
        }
        self.events['encoder'] = asyncio.Event()

    async def _start_monitor(self):
        loop = asyncio.get_event_loop()

        # initialize button monitor tasks
        loop.create_task(self._poll_buttons())

        # initialize rotary monitor task
        loop.create_task(self._poll_position())

    async def _poll_buttons(self):
        button_map = {}
        button_mask = 0
        last_states = {}
        for name, pin in ANO_BUTTON_MAP.items():
            mask = 1 << pin
            button_map[mask] = name
            button_mask |= mask
            last_states[name] = mask
        self.seesaw.pin_mode_bulk(button_mask, self.seesaw.INPUT_PULLUP)
        last_full_state = self.seesaw.digital_read_bulk(button_mask)
        while True:
            full_state = self.seesaw.digital_read_bulk(button_mask)
            if full_state != last_full_state:
                for mask, name in button_map.items():
                    new_state = full_state & mask
                    if new_state != last_states[name]:
                        direction = 'release' if new_state else 'press'
                        self.events[f'{name}_{direction}'].set()
                        last_states[name] = new_state
                last_full_state = full_state

            await asyncio.sleep_ms(50)

    async def _poll_position(self):
        encoder = self.encoder
        pos = encoder.position
        while True:
            cur_pos = encoder.position
            if cur_pos != pos:
                pos = cur_pos
                self.events['encoder'].set()
                while self.events['encoder'].is_set():
                    await asyncio.sleep_ms(10)
            else:
                await asyncio.sleep_ms(10)


class QualiaButtons:
    @classmethod
    async def new(cls, bus, addr=0x3f):
        await _scan(bus, addr)

        pcf = adafruit_pca9554.PCA9554(bus, address=addr)
        btn_dn = pcf.get_pin(board.BTN_DN)
        btn_dn.switch_to_input(pull=digitalio.Pull.UP)

        btn_up = pcf.get_pin(board.BTN_UP)
        btn_up.switch_to_input(pull=digitalio.Pull.UP)

        obj = cls(btn_dn, btn_up)
        await obj._start_monitors()
        return obj

    def __init__(self, btn_dn, btn_up):
        self._btn_dn = btn_dn
        self._btn_up = btn_up
        self.events = {
            'up_press': asyncio.Event(),
            'up_release': asyncio.Event(),
            'dn_press': asyncio.Event(),
            'dn_release': asyncio.Event(),
        }

    async def _start_monitors(self):
        loop = asyncio.get_event_loop()
        loop.create_task(self._poll_button(self._btn_dn, self.events['dn_press'], self.events['dn_release']))
        loop.create_task(self._poll_button(self._btn_up, self.events['up_press'], self.events['up_release']))

    async def _poll_button(self, btn, press, release):
        last_state = btn.value
        while True:
            cur_state = btn.value
            if cur_state != last_state:
                if cur_state is False:
                    press.set()
                else:
                    release.set()
                last_state = cur_state

            await asyncio.sleep_ms(50)
