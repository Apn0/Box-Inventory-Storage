import timeit
import re

# Old implementation
CATEGORY_RULES_OLD = [
    ("mcu",        r"esp32|esp8266|xiao|microcontroller|\bmcu\b"),
    ("sensor",     r"\bmq-|mq gas|guva|heart-rate|neo-6m|gps|ens160|aht2|gyro|accelerom|"
                   r"mpu6050|hc-sr04|tilt sensor|tof|vl53|veml|hall sensor|reed |"
                   r"vibration (sensor|switch)|pressure sensor|load cell|current sensor|"
                   r"current transformer|ina219|audio-wave|lm393|magnetic switch|rd-03d|"
                   r"capacitive touch|ir receiver|laser sensor|mps20n|voltage sensor|"
                   r"coil-type vibration|pressure-sensitive"),
    ("power",      r"charger|converter|buck|boost|step-up|step-down|mt3608|mini-360|hw-187|"
                   r"mp1584|cr6030|pd trigger|fast-charge|solar charge|18650|battery|"
                   r"batteries|lr44|\bac/dc\b|power module|power meter|v meter|"
                   r"level indicator|usb-a power"),
    ("driver",     r"tmc2209|uln2003|motor driver|h-bridge|tc1508|mosfet|relay|\bssr\b|"
                   r"pwm controller|speed controller|stepper driver|xy-mos|lr7843"),
    ("motor",      r"stepper motor|servo|dc motor|gear motor|brushed dc|vibration motor|"
                   r"\bfan\b|micro dc"),
    ("display",    r"oled|7-seg|\bled\b|leds|cob|rgb|traffic-light|candle|flasher|display"),
    ("comms",      r"wi-fi|wifi|uart|ir transmitter|nfc|sim card|rj-45|tracker tag|"
                   r"walkie|receiver \(dongle\)|wireless mouse|laser diode"),
    ("interface",  r"ads1115|\badc\b|hx711|pcm1808|i2s|555 timer|breakout|serial adapter|"
                   r"usb-to-ttl|hw-477|sku7810"),
    ("switch",     r"switch|button|potentiometer|encoder|knob|key lock|\bkeys?\b|"
                   r"navigation tactile|piezoelectric spark"),
    ("connector",  r"xt60|usb|hdmi|barrel|header pin|terminal|alligator|wire connector|"
                   r"kroonsteentje|audio plug|adapter|coupling|connector|iec panel|"
                   r"strip connector|cable reel"),
    ("fastener",   r"bolt|screw|\bnuts?\b|washer|standoff|tap bits|drill|countersink|"
                   r"barrel nut|mounting hardware|lock nut|lock washer"),
    ("mechanical", r"gear|pulley|belt|bearing|idler|rail|carriage|tube|tubing|heatsink|"
                   r"disk|bracket|mechanical parts|nozzle|clamp|padlock|clip|"
                   r"elastic band|spacer"),
    ("tool",       r"tool|bit set|measuring tape|keycap remover|radiator valve|tape|"
                   r"lens kit|hemming"),
    ("material",   r"scrap|shavings|sawdust|flakes|granules|seeds|salts|foam|earplug|"
                   r"popsicle|hot-glue|shoelace|gemstone|coil|sticker|label"),
]
DEFAULT_CATEGORY = "misc"

def categorise_old(name: str, note: str) -> str:
    hay = f"{name} {note}".lower()
    for cat, pattern in CATEGORY_RULES_OLD:
        if re.search(pattern, hay):
            return cat
    return DEFAULT_CATEGORY


# New implementation
CATEGORY_RULES_NEW = [
    (cat, re.compile(pattern)) for cat, pattern in CATEGORY_RULES_OLD
]

def categorise_new(name: str, note: str) -> str:
    hay = f"{name} {note}".lower()
    for cat, pattern in CATEGORY_RULES_NEW:
        if pattern.search(hay):
            return cat
    return DEFAULT_CATEGORY


# Test dataset
test_cases = [
    ("ESP32 module", "Wi-Fi enabled"),
    ("Generic sensor", "No clear type"),
    ("Unknown part", "Just some stuff"),
    ("TMC2209", "Stepper driver"),
    ("M3 bolt", "Fastener stuff"),
]

def run_old():
    for name, note in test_cases:
        categorise_old(name, note)

def run_new():
    for name, note in test_cases:
        categorise_new(name, note)

print("Baseline (Old) Time:", timeit.timeit("run_old()", globals=globals(), number=100000))
print("Optimized (New) Time:", timeit.timeit("run_new()", globals=globals(), number=100000))
