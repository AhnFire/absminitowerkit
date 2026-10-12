import time
import board
from rainbowio import colorwheel
import neopixel

# pixels = neopixel.NeoPixel(board.D18, 4)  # D18 means connect to GPIO18 on Raspberry Pi. 4 means 4 leds
# led on back of OLED driver board, (255, 0 , 0 ) is RGB format of the light, value from 0-255,
#  (255,0,0) means (red, green, blue) it will turn on the light to red color. (0, 0, 0 ) will turn off the color.

# Update to match the pin connected to your NeoPixels
pixel_pin = board.D18
# Update to match the number of NeoPixels you have connected
num_pixels = 4


pixels = neopixel.NeoPixel(pixel_pin, num_pixels, brightness=0.3, auto_write=False)


def color_chase(color, wait):
    for i in range(num_pixels):
        pixels[i] = color
        time.sleep(wait)
        pixels.show()
    time.sleep(0.5)


def rainbow_cycle(wait):
    for j in range(255):
        for i in range(num_pixels):
            rc_index = (i * 256 // num_pixels) + j
            pixels[i] = colorwheel(rc_index & 255)
        pixels.show()
        time.sleep(wait)


RED = (255, 0, 0)
YELLOW = (255, 150, 0)
GREEN = (0, 255, 0)
CYAN = (0, 255, 255)
BLUE = (0, 0, 255)
PURPLE = (180, 0, 255)

while True:
    pixels.fill(RED)
    pixels.show()
    time.sleep(1)  # Increase or decrease to change the speed of the solid color change.
    pixels.fill(GREEN)
    pixels.show()
    time.sleep(1)
    pixels.fill(BLUE)
    pixels.show()
    time.sleep(1)

    color_chase(RED, 0.3)  # Increase the number to slow down the color chase
    color_chase(YELLOW, 0.3)
    color_chase(GREEN, 0.3)
    color_chase(CYAN, 0.3)
    color_chase(BLUE, 0.3)
    color_chase(PURPLE, 0.3)

    for x in range(5):
        rainbow_cycle(0.1)  # Increase the number to slow down the rainbow