from .slider import Slider


class Volume(Slider):
    @property
    def volume(self):
        return int(self.position * 100)

    @volume.setter
    def volume(self, new_vol):
        print(f'{new_vol=} {new_vol/100}')
        self.position = new_vol / 100

    def __init__(self, *args, **kwargs):
        super().__init__(orientation='vertical', **kwargs)
