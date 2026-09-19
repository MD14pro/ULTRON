import math
import random
import time
from adafruit_ili9341 import ILI9341
from adafruit_display_shapes.roundrect import RoundRect
from adafruit_display_shapes.triangle import Triangle
import board
import displayio
import smbus2

# Handle FourWire import compatibility
try:
  from fourwire import FourWire
except ImportError:
  from displayio import FourWire

displayio.release_displays()
spi = board.SPI()

# Initialize direct I2C using smbus2
print('Initializing MPU 6050 via smbus2...')
bus = smbus2.SMBus(1)
MPU6050_ADDR = 0x68

try:
  bus.write_byte_data(MPU6050_ADDR, 0x6B, 0)
  print('MPU 6050 Awakened Successfully!')
except Exception as e:
  print(f'Warning/Error waking MPU6050: {e}')


def read_mpu_accel():
  try:
    data = bus.read_i2c_block_data(MPU6050_ADDR, 0x3B, 6)

    def convert_word(high, low):
      val = (high << 8) + low
      if val >= 0x8000:
        val = -((65535 - val) + 1)
      return val

    ax = convert_word(data[0], data[1]) / 16384.0 * 9.81
    ay = convert_word(data[2], data[3]) / 16384.0 * 9.81
    az = convert_word(data[4], data[5]) / 16384.0 * 9.81
    return (ax, ay, az)
  except Exception:
    return (0.0, 0.0, 9.81)


# Setup Display (Baudrate boosted to 48MHz for ultra-fast refresh)
display_bus = FourWire(
    spi,
    command=board.D24,
    chip_select=board.CE0,
    reset=board.D25,
    baudrate=48000000,
)
display = ILI9341(display_bus, width=320, height=240, rotation=90)

# Colors
# Dark Gunmetal / Vibranium Alloy Background
VIBRANIUM_GREY = 0x2A2C30  
# Glowing Red Eyes (Hardware swap fix)
RED_EYES = 0x0000FF  


def create_theme_group(elements):
  """Helper function to create display groups fast and clean"""
  group = displayio.Group()
  bg_bitmap = displayio.Bitmap(320, 240, 1)
  bg_palette = displayio.Palette(1)
  bg_palette[0] = VIBRANIUM_GREY
  group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))
  
  for element in elements:
    group.append(element)
  return group


# Pre-build all Expression Groups for instant switching
# 1. Neutral Eyes & Closed Mouth
neutral_group = create_theme_group([
    RoundRect(75, 65, 50, 100, r=15, fill=RED_EYES),
    RoundRect(185, 65, 50, 100, r=15, fill=RED_EYES),
    RoundRect(130, 200, 60, 8, r=4, fill=RED_EYES)  # Straight closed mouth
])

# 2. Blink Eyes (Thin slits) & Closed Mouth
blink_group = create_theme_group([
    RoundRect(75, 110, 50, 10, r=3, fill=RED_EYES),
    RoundRect(185, 110, 50, 10, r=3, fill=RED_EYES),
    RoundRect(130, 200, 60, 8, r=4, fill=RED_EYES)
])

# 3. Dizzy Eyes & 'O' Shaped Mouth
dizzy_group = create_theme_group([
    RoundRect(70, 110, 60, 30, r=5, fill=RED_EYES),
    RoundRect(180, 110, 60, 30, r=5, fill=RED_EYES),
    RoundRect(140, 195, 40, 15, r=5, fill=RED_EYES)  # O-mouth
])

# 4. Angry Eyes (Slanted) & Mouth CLOSED
angry_closed_group = create_theme_group([
    RoundRect(75, 65, 50, 100, r=15, fill=RED_EYES),
    RoundRect(185, 65, 50, 100, r=15, fill=RED_EYES),
    Triangle(60, 50, 140, 50, 140, 115, fill=VIBRANIUM_GREY),  # Left Mask
    Triangle(170, 50, 250, 50, 170, 115, fill=VIBRANIUM_GREY), # Right Mask
    RoundRect(130, 200, 60, 8, r=4, fill=RED_EYES)  # Closed mouth
])

# 5. Angry Eyes (Slanted) & Mouth OPEN (Talking)
angry_open_group = create_theme_group([
    RoundRect(75, 65, 50, 100, r=15, fill=RED_EYES),
    RoundRect(185, 65, 50, 100, r=15, fill=RED_EYES),
    Triangle(60, 50, 140, 50, 140, 115, fill=VIBRANIUM_GREY),  # Left Mask
    Triangle(170, 50, 250, 50, 170, 115, fill=VIBRANIUM_GREY), # Right Mask
    RoundRect(130, 190, 60, 24, r=8, fill=RED_EYES)  # Wide Open Mouth
])

# Start with Neutral
display.root_group = neutral_group

print('\n--- Vibranium Ultron Protocol Active ---')
print('Features: Dark Alloy Background, Blinking, High-Speed Refresh, Angry Talking Animation')

next_blink_time = time.time() + random.uniform(2, 5)
next_talk_time = 0
is_mouth_open = False

try:
  while True:
    ax, ay, az = read_mpu_accel()
    total_accel = math.sqrt(ax**2 + ay**2 + az**2)
    current_time = time.time()

    # Priority 1: High Magnitude Shake (Dizzy)
    if total_accel > 14.0:
      display.root_group = dizzy_group
      time.sleep(0.6)  
      display.root_group = neutral_group
      next_blink_time = time.time() + random.uniform(2, 4)

    # Priority 2: Tilt Detection for Angry / Talking state
    elif abs(ax) > 6.0 or abs(ay) > 6.0:
      # Animate the mouth to simulate talking while angry
      if current_time >= next_talk_time:
        is_mouth_open = not is_mouth_open
        display.root_group = angry_open_group if is_mouth_open else angry_closed_group
        # Randomize talking speed slightly for realism (fast open/close)
        next_talk_time = current_time + random.uniform(0.1, 0.25)

    # Priority 3: Normal State with Natural Blinking
    else:
      if display.root_group != neutral_group and display.root_group != blink_group:
        display.root_group = neutral_group

      # Execute Blink
      if current_time >= next_blink_time:
        display.root_group = blink_group  
        time.sleep(0.15)  
        display.root_group = neutral_group  
        next_blink_time = time.time() + random.uniform(2.5, 6.0)

    # Shorter sleep for much faster sensor polling and responsiveness
    time.sleep(0.02)

except KeyboardInterrupt:
  print('\nExiting safely.')
