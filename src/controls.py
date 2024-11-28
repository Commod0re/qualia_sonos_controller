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
    @classmethod
    async def new(cls, bus, addr=0x49):
        # scan i2c bus for our device
        while not bus.try_lock():
            await asyncio.sleep(0.1)
        if addr not in bus.scan():
            raise Exception(f'no i2c device found at 0x{addr:02x}')
        bus.unlock()

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
                        print(f'{name}_{direction}')
                        self.events[f'{name}_{direction}'].set()
                        last_states[name] = new_state
                last_full_state = full_state

            await asyncio.sleep_ms(100)

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
