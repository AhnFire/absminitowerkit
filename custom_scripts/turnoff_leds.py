import board
from neopixel import NeoPixel

np = NeoPixel(board.D18, 4)

np.fill((0,0,0))
