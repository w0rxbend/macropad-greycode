// Pins mirror board.toml; tools/check_pins.py keeps them in step.
#pragma once

#define RP2040_BOOTLOADER_DOUBLE_TAP_RESET
#define RP2040_BOOTLOADER_DOUBLE_TAP_RESET_TIMEOUT 500U

#define I2C_DRIVER I2CD1
#define I2C1_SDA_PIN GP14
#define I2C1_SCL_PIN GP15

// 1.3" 128x64 module; SH1106 needs the 2-column offset
#define OLED_DISPLAY_128X64
#define OLED_IC OLED_IC_SH1106
#define OLED_COLUMN_OFFSET 2
#define OLED_TIMEOUT 0 // the host decides what the screen shows; never blank it

// Index of the first edge LED in keyboard.json's rgb_matrix.layout
#define GREYCODE_EDGE_FIRST 9
#define GREYCODE_EDGE_COUNT 6
