#!/usr/bin/env python3

import json
import os
import re
import subprocess
import sys
import threading
import time

from PIL import Image, ImageDraw, ImageFont
import adafruit_ssd1306
from board import SCL, SDA
import busio
from gpiozero import Button
import paho.mqtt.client as mqtt

# Create the I2C interface.
i2c = busio.I2C(SCL, SDA)

# Create the SSD1306 OLED class.
# The first two parameters are the pixel width and pixel height.  Change these
# to the right size for your display!
disp = adafruit_ssd1306.SSD1306_I2C(128, 32, i2c)

# Leaving the OLED on for a long period of time can damage it
# Set these to prevent OLED burn in
DISPLAY_ON  = 20

# Clear display.
disp.fill(0)
disp.show()

# Create blank image for drawing.
# Make sure to create image with mode '1' for 1-bit color.
width = disp.width
height = disp.height
image = Image.new('1', (width, height))

# Get drawing object to draw on image.
draw = ImageDraw.Draw(image)

# Draw a black filled box to clear the image.
draw.rectangle((0, 0, width, height), outline=0, fill=0)

# Draw some shapes.
# First define some constants to allow easy resizing of shapes.
padding = -2
top = padding
bottom = height - padding
# Move left to right keeping track of the current x position
# for drawing shapes.
x = 0

#font = ImageFont.load_default()
# Load nice silkscreen font
font = ImageFont.truetype('/home/pi/winecase/slkscr.ttf', 8)

DISPLAY_TIME = 20
SLEEP = 0.1

# display a warning if not root
if os.getuid() != 0:
    print("Error: need to be root to access.")
    sys.exit(2)


class Metadata(threading.Thread):

    def __init__(self):
        threading.Thread.__init__(self)
        self.daemon = True
        # need to install https://github.com/mikebrady/shairport-sync-metadata-reader
        self.command = "/usr/local/bin/shairport-sync-metadata-reader < /tmp/shairport-sync-metadata"
        self.lock = threading.Lock()
        self.metadata = {'Title': '', 'Artist': '', 'Album Name': '', 'update_time': time.time()}

    def get_metadata(self):
        with self.lock: return self.metadata

    def run(self):
        try:
            process = os.popen(self.command,mode='r')
            while True:
                time.sleep(SLEEP)
                try:
                    output = process.readline().rstrip()
                    if output:
                        for key in ["Artist", "Title", "Album Name"]:
                            regex = key + ': "(.*)".'
                            match = re.match(regex,output)
                            if match:
                                # clean the special characters from the metadata as dot3k can't display "Með blóðnasir by Sigur Rós"!
                                # clean_match = unicodedata.normalize('NFKD', match.group(1)).encode('ASCII', 'ignore').decode('UTF-8')
                                self.metadata[key] = match.group(1)
                        self.metadata['update_time'] = time.time()
                        print("Now Playing: '" + self.metadata['Title'] + " - " + self.metadata['Artist'] + "'")
                except Exception as error:
                    print("Error:", error)
                    time.sleep(1)
        except OSError as error:
            print("Error:", error)
            sys.exit(1)


def turn_off_display():
    disp.fill(0)
    disp.show()

message = ""

light_power = True

def on_message(client, userdata, message):
    global light_power
    topic = message.topic
    value = str(message.payload.decode("utf-8"))
    print("received message: ", topic, value)

    if topic == "homie/d550fe00/light/power":
        light_power = value == "true"

def on_connect(client, userdata, flags, rc):
    print("Connected with result code "+str(rc))
    client.subscribe("homie/d550fe00/light/power")

username = os.environ.get("MQTT_USERNAME")
password = os.environ.get("MQTT_PASSWORD")

client = mqtt.Client("winecase")
client.tls_set()
client.username_pw_set(username, password)
client.connect("m20.cloudmqtt.com", port=20685) 

client.on_connect = on_connect
client.on_message = on_message

client.loop_start()

def when_pressed():
    global message
    message = "will shutdown in 6s"

def when_released(btn):
    global message
    global light_power
    message = ""
    if not btn.was_held:
        light_power = not light_power
        client.publish("homie/d550fe00/light/power/set", json.dumps(light_power))
        return
    btn.was_held = False

    print("shutdown")
    turn_off_display()
    client.loop_stop()
    os.system("sudo poweroff")

def shutdown(btn):
    btn.was_held = True

Button.was_held = False
# https://gpiozero.readthedocs.io/en/stable/recipes.html#pin-numbering
btn = Button(23, hold_time=6)
btn.when_held = shutdown
btn.when_pressed = when_pressed
btn.when_released = when_released

def main():
    m = Metadata() # setup metadata reader process
    m.start() # start the process

    # Shell scripts for system monitoring from here:
    # https://unix.stackexchange.com/questions/119126/command-to-display-memory-usage-disk-usage-and-cpu-load
    cmd = "hostname -I | cut -d\' \' -f1"
    IP = subprocess.check_output(cmd, shell=True).decode("utf-8")
    cmd = "top -bn1 | grep load | awk '{printf \"CPU Load: %.2f\", $(NF-2)}'"
    CPU = subprocess.check_output(cmd, shell=True).decode("utf-8")
    cmd = "free -m | awk 'NR==2{printf \"Mem: %s/%s MB  %.2f%%\", $3,$2,$3*100/$2 }'"
    MemUsage = subprocess.check_output(cmd, shell=True).decode("utf-8")
    cmd = "df -h | awk '$NF==\"/\"{printf \"Disk: %d/%d GB  %s\", $3,$2,$5}'"
    Disk = subprocess.check_output(cmd, shell=True).decode("utf-8")

    draw.text((x, top+0), "IP: "+IP, font=font, fill=255)
    draw.text((x, top+8), CPU, font=font, fill=255)
    draw.text((x, top+16), MemUsage, font=font, fill=255)
    draw.text((x, top+25), Disk, font=font, fill=255)

    disp.image(image)
    disp.show()

    time.sleep(5)

    # main loop, catch Ctrl+C to exit gracefully
    try:
        while True:
            # Draw a black filled box to clear the image.
            draw.rectangle((0, 0, width, height), outline=0, fill=0)

            # get the current track info
            metadata = m.get_metadata()
            if metadata['update_time'] + DISPLAY_TIME > time.time():
                draw.text((x, top+8),     str(metadata['Title']), font=font, fill=255)
                draw.text((x, top+16),    str(metadata['Artist']),  font=font, fill=255)
                draw.text((x, top+25),    str(metadata['Album Name']),  font=font, fill=255)

            if message:
                draw.text((x, top), str(message), font=font, fill=255)

            disp.image(image)
            disp.show()

            time.sleep(SLEEP)


    except KeyboardInterrupt:
        turn_off_display()
        client.loop_stop()
        sys.exit(0)

# ------------------------------------------------------- #

if __name__ == '__main__':
    main()
