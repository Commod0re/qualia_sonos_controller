import asyncio
from adafruit_seesaw import seesaw, digitalio, rotaryio


ANO_BUTTON_MAP = {
    'select': 1,
    'up': 2,
    'left': 3,
    'down': 4,
    'right': 5,
}


class AnoRotary:
    def __init__(self, bus, addr=0x49):
        self.i2c = bus
        self.addr = addr
        self.seesaw = None
        self.encoder = None
        # prepare events
        self.events = {
            f'{name}_{direction}': asyncio.Event()
            for name in ANO_BUTTON_MAP
            for direction in ('press', 'release')
        }
        self.events['encoder'] = asyncio.Event()

        # do async init
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self._init())

    async def _init(self):
        # get an asyncio loop reference
        loop = asyncio.get_event_loop()

        # scan i2c bus for our device
        while not self.i2c.try_lock():
            await asyncio.sleep(0.1)
        if self.addr not in self.i2c.scan():
            raise Exception(f'no i2c device found at 0x{self.addr:02x}')
        self.i2c.unlock()

        # initialize seesaw
        self.seesaw = seesaw.Seesaw(self.i2c, addr=self.addr)

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
        while True:
            full_state = self.seesaw.digital_read_bulk(button_mask)
            for mask, name in button_map.items():
                new_state = full_state & mask
                if new_state != last_states[name]:
                    direction = 'release' if new_state else 'press'
                    print(f'{name}_{direction}')
                    self.events[f'{name}_{direction}'].set()
                    last_states[name] = new_state

            await asyncio.sleep_ms(300)

    async def _poll_position(self):
        self.encoder = encoder = rotaryio.IncrementalEncoder(self.seesaw)
        pos = encoder.position
        while True:
            cur_pos = encoder.position
            if cur_pos != pos:
                pos = cur_pos
                self.events['encoder'].set()
            await asyncio.sleep_ms(50)
