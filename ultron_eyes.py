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

class UltronFace:
    def __init__(self):
        displayio.release_displays()
        self.spi = board.SPI()
        
        # Colors
        self.VIBRANIUM_GREY = 0x2A2C30  
        self.RED_EYES = 0x0000FF  

        # Setup I2C & MPU6050
        print('[Ultron] Initializing MPU 6050...')
        self.bus = smbus2.SMBus(1)
        self.MPU6050_ADDR = 0x68
        try:
            self.bus.write_byte_data(self.MPU6050_ADDR, 0x6B, 0)
        except Exception as e:
            print(f'[Ultron] Warning waking MPU6050: {e}')

        # Setup Display
        self.display_bus = FourWire(
            self.spi, command=board.D24, chip_select=board.CE0,
            reset=board.D25, baudrate=48000000,
        )
        self.display = ILI9341(self.display_bus, width=320, height=240, rotation=90)

        # Build Groups
        self._build_groups()
        self.display.root_group = self.neutral_group

        # State Variables
        self.next_blink_time = time.time() + random.uniform(2, 5)
        self.next_talk_time = 0
        self.is_mouth_open = False
        
        # Calibration for "Ched Chad" detection
        self.base_x, self.base_y = 0.0, 0.0
        self.calibrate_rest_position()

    def _build_groups(self):
        def create_group(elements):
            group = displayio.Group()
            bg_bitmap = displayio.Bitmap(320, 240, 1)
            bg_palette = displayio.Palette(1)
            bg_palette[0] = self.VIBRANIUM_GREY
            group.append(displayio.TileGrid(bg_bitmap, pixel_shader=bg_palette))
            for el in elements: group.append(el)
            return group

        self.neutral_group = create_group([
            RoundRect(75, 65, 50, 100, r=15, fill=self.RED_EYES),
            RoundRect(185, 65, 50, 100, r=15, fill=self.RED_EYES),
            RoundRect(130, 200, 60, 8, r=4, fill=self.RED_EYES)
        ])
        
        self.blink_group = create_group([
            RoundRect(75, 110, 50, 10, r=3, fill=self.RED_EYES),
            RoundRect(185, 110, 50, 10, r=3, fill=self.RED_EYES),
            RoundRect(130, 200, 60, 8, r=4, fill=self.RED_EYES)
        ])
        
        self.dizzy_group = create_group([
            RoundRect(70, 110, 60, 30, r=5, fill=self.RED_EYES),
            RoundRect(180, 110, 60, 30, r=5, fill=self.RED_EYES),
            RoundRect(140, 195, 40, 15, r=5, fill=self.RED_EYES)
        ])
        
        self.angry_closed_group = create_group([
            RoundRect(75, 65, 50, 100, r=15, fill=self.RED_EYES),
            RoundRect(185, 65, 50, 100, r=15, fill=self.RED_EYES),
            Triangle(60, 50, 140, 50, 140, 115, fill=self.VIBRANIUM_GREY),
            Triangle(170, 50, 250, 50, 170, 115, fill=self.VIBRANIUM_GREY),
            RoundRect(130, 200, 60, 8, r=4, fill=self.RED_EYES)
        ])
        
        self.angry_open_group = create_group([
            RoundRect(75, 65, 50, 100, r=15, fill=self.RED_EYES),
            RoundRect(185, 65, 50, 100, r=15, fill=self.RED_EYES),
            Triangle(60, 50, 140, 50, 140, 115, fill=self.VIBRANIUM_GREY),
            Triangle(170, 50, 250, 50, 170, 115, fill=self.VIBRANIUM_GREY),
            RoundRect(130, 190, 60, 24, r=8, fill=self.RED_EYES)
        ])

    def calibrate_rest_position(self):
        print('[Ultron] Calibrating default resting position... DO NOT MOVE.')
        sum_x, sum_y = 0, 0
        samples = 20
        for _ in range(samples):
            ax, ay, _ = self.read_accel()
            sum_x += ax
            sum_y += ay
            time.sleep(0.05)
        self.base_x = sum_x / samples
        self.base_y = sum_y / samples
        print(f'[Ultron] Baseline set -> X: {self.base_x:.2f}, Y: {self.base_y:.2f}')

    def read_accel(self):
        try:
            data = self.bus.read_i2c_block_data(self.MPU6050_ADDR, 0x3B, 6)
            def conv(h, l):
                v = (h << 8) + l
                return -((65535 - v) + 1) if v >= 0x8000 else v
            ax = conv(data[0], data[1]) / 16384.0 * 9.81
            ay = conv(data[2], data[3]) / 16384.0 * 9.81
            az = conv(data[4], data[5]) / 16384.0 * 9.81
            return (ax, ay, az)
        except Exception:
            return (self.base_x, self.base_y, 9.81)

    def tick(self, force_talk=False):
        """
        Call this function rapidly in your main script's loop.
        force_talk: Pass True if your AI is speaking via speaker to move mouth.
        """
        ax, ay, az = self.read_accel()
        total_accel = math.sqrt(ax**2 + ay**2 + az**2)
        current_time = time.time()

        # Calculate deviation from the calibrated baseline
        delta_x = abs(ax - self.base_x)
        delta_y = abs(ay - self.base_y)

        # 1. SHAKE: Extreme movement
        if total_accel > 14.0:
            self.display.root_group = self.dizzy_group
            time.sleep(0.5)
            self.display.root_group = self.neutral_group
            self.next_blink_time = current_time + random.uniform(2, 4)

        # 2. CHED CHAD: Trigger Angry if tilted > 4.0 from its default rest position
        elif delta_x > 4.0 or delta_y > 4.0 or force_talk:
            if current_time >= self.next_talk_time:
                self.is_mouth_open = not self.is_mouth_open
                self.display.root_group = self.angry_open_group if self.is_mouth_open else self.angry_closed_group
                self.next_talk_time = current_time + random.uniform(0.1, 0.25)

        # 3. NORMAL STATE: Natural Blinking
        else:
            if self.display.root_group not in (self.neutral_group, self.blink_group):
                self.display.root_group = self.neutral_group

            if current_time >= self.next_blink_time:
                self.display.root_group = self.blink_group  
                time.sleep(0.15)  
                self.display.root_group = self.neutral_group  
                self.next_blink_time = current_time + random.uniform(2.5, 6.0)
