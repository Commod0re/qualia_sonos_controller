import displayio
from adafruit_qualia import Qualia
from adafruit_qualia.graphics import Displays

displayio.release_displays()
qualia = Qualia(Displays.SQUARE40)
qualia.display.root_group = displayio.CIRCUITPYTHON_TERMINAL
