//! Host-link frames. Wire format: docs/protocol.md.
//! The firmware side is firmware/greycode/hostlink.c; both test against firmware/test/vectors.txt.

use serde::Deserialize;

pub const REPORT: usize = 32;
pub const ID: u8 = 0xC7;
pub const PROTO: u8 = 1;
pub const KEYS: usize = 9;
const NAME_LEN: usize = 16;
const LABEL_LEN: usize = 6;
const TEXT_LEN: usize = 20;
const NO_LAYER: u8 = 0xFF;

const HELLO: u8 = 0x01;
const HEARTBEAT: u8 = 0x02;
const PROFILE: u8 = 0x03;
const LABEL: u8 = 0x04;
const ALERT: u8 = 0x05;
const KEY_LEDS: u8 = 0x06;
const EVT_HOST_KEY: u8 = 0x81;

pub type Frame = [u8; REPORT];
pub type Rgb = [u8; 3];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Level {
    Clear = 0,
    Info = 1,
    Ok = 2,
    Warn = 3,
    Error = 4,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Pattern {
    Solid = 0,
    Pulse = 1,
    Blink = 2,
}

#[derive(Clone, Debug, PartialEq)]
pub struct Alert {
    pub level: Level,
    pub pattern: Pattern,
    /// None: the firmware's colour for the level.
    pub color: Option<Rgb>,
    /// 0: until cleared.
    pub timeout_s: u16,
    pub text: String,
}

/// What the pad sends: replies to our frames and HOST(n) key events.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Incoming {
    Hello { proto: u8, layers: u8, keys: u8 },
    Reply { cmd: u8, status: u8 },
    HostKey { n: u8, pressed: bool },
}

fn frame(cmd: u8) -> Frame {
    let mut f = [0u8; REPORT];
    f[0] = ID;
    f[1] = cmd;
    f
}

/// The pad shows printable ASCII only; anything else becomes '?'.
fn put_text(dst: &mut [u8], text: &str) {
    for (d, c) in dst.iter_mut().zip(text.chars()) {
        *d = if c.is_ascii_graphic() || c == ' ' { c as u8 } else { b'?' };
    }
}

pub fn hello() -> Frame {
    let mut f = frame(HELLO);
    f[2] = PROTO;
    f
}

pub fn heartbeat() -> Frame {
    frame(HEARTBEAT)
}

pub fn profile(layer: Option<u8>, accent: Rgb, name: &str) -> Frame {
    let mut f = frame(PROFILE);
    f[2] = layer.unwrap_or(NO_LAYER);
    f[3..6].copy_from_slice(&accent);
    put_text(&mut f[6..6 + NAME_LEN], name);
    f
}

pub fn label(index: u8, text: &str) -> Frame {
    let mut f = frame(LABEL);
    f[2] = index;
    put_text(&mut f[3..3 + LABEL_LEN], text);
    f
}

pub fn alert(a: &Alert) -> Frame {
    let mut f = frame(ALERT);
    f[2] = a.level as u8;
    if a.level == Level::Clear {
        return f;
    }
    f[3] = a.pattern as u8;
    f[4..7].copy_from_slice(&a.color.unwrap_or([0, 0, 0]));
    f[7..9].copy_from_slice(&a.timeout_s.to_le_bytes());
    put_text(&mut f[9..9 + TEXT_LEN], &a.text);
    f
}

/// Colour the keys in `mask` (bit n = key n, row by row); `None` gives them back to the RGB effect.
pub fn key_leds(mask: u16, color: Option<Rgb>) -> Frame {
    let mut f = frame(KEY_LEDS);
    f[2..4].copy_from_slice(&mask.to_le_bytes());
    if let Some(rgb) = color {
        f[4] = 1;
        f[5..8].copy_from_slice(&rgb);
    }
    f
}

/// None for anything that is not a host-link report (VIA and Vial replies share the interface).
pub fn parse(report: &[u8]) -> Option<Incoming> {
    if report.len() < 6 || report[0] != ID {
        return None;
    }
    Some(match report[1] {
        EVT_HOST_KEY => Incoming::HostKey { n: report[2], pressed: report[3] != 0 },
        HELLO if report[2] == 0 => Incoming::Hello { proto: report[3], layers: report[4], keys: report[5] },
        cmd => Incoming::Reply { cmd, status: report[2] },
    })
}

/// "#rrggbb" or "rrggbb".
pub fn parse_rgb(s: &str) -> Result<Rgb, String> {
    let hex = s.strip_prefix('#').unwrap_or(s);
    let bad = || format!("colour {s:?} is not #rrggbb");
    if hex.len() != 6 || !hex.is_ascii() {
        return Err(bad());
    }
    let byte = |i: usize| u8::from_str_radix(&hex[i..i + 2], 16).map_err(|_| bad());
    Ok([byte(0)?, byte(2)?, byte(4)?])
}

#[cfg(test)]
mod tests {
    use super::*;

    const VECTORS: &str = include_str!("../../firmware/test/vectors.txt");

    fn vector(name: &str) -> Frame {
        let line = VECTORS
            .lines()
            .find(|l| l.split_whitespace().next() == Some(name))
            .unwrap_or_else(|| panic!("vector {name} missing"));
        let mut f = [0u8; REPORT];
        for (d, hex) in f.iter_mut().zip(line.split_whitespace().skip(1)) {
            *d = u8::from_str_radix(hex, 16).unwrap();
        }
        f
    }

    #[test]
    fn frames_match_the_firmware_vectors() {
        assert_eq!(hello(), vector("hello"));
        assert_eq!(heartbeat(), vector("heartbeat"));
        assert_eq!(profile(Some(1), [0xff, 0x88, 0], "FreeCAD"), vector("profile_freecad"));
        assert_eq!(profile(None, [0, 0, 0], ""), vector("profile_none"));
        assert_eq!(label(4, "Pad"), vector("label_4_pad"));
        let warn = Alert {
            level: Level::Warn,
            pattern: Pattern::Blink,
            color: None,
            timeout_s: 10,
            text: "Build failed".into(),
        };
        assert_eq!(alert(&warn), vector("alert_warn"));
        assert_eq!(alert(&Alert { level: Level::Clear, ..warn }), vector("alert_clear"));
        assert_eq!(key_leds(0b101, Some([0, 0xff, 0])), vector("keys_set_0_2"));
        assert_eq!(key_leds(0x1ff, None), vector("keys_clear_all"));
    }

    #[test]
    fn parses_host_key_event_and_replies() {
        assert_eq!(parse(&vector("host_key_3_down")), Some(Incoming::HostKey { n: 3, pressed: true }));
        let mut hello_reply = [0u8; REPORT];
        hello_reply[..6].copy_from_slice(&[ID, HELLO, 0, PROTO, 16, 9]);
        assert_eq!(parse(&hello_reply), Some(Incoming::Hello { proto: 1, layers: 16, keys: 9 }));
        assert_eq!(parse(&[ID, LABEL, 2, 0, 0, 0]), Some(Incoming::Reply { cmd: LABEL, status: 2 }));
        assert_eq!(parse(&[0xFE, 0, 0, 0, 0, 0]), None, "a Vial reply is not ours");
        assert_eq!(parse(&[ID, 1]), None, "short read");
    }

    #[test]
    fn text_is_truncated_and_ascii_only() {
        let f = profile(Some(2), [0, 0, 0], "Ünïcode name that is far too long");
        assert_eq!(&f[6..22], b"?n?code name tha");
        assert_eq!(f[22], 0);
    }

    #[test]
    fn rgb_parsing() {
        assert_eq!(parse_rgb("#ff8800"), Ok([0xff, 0x88, 0]));
        assert_eq!(parse_rgb("00ff00"), Ok([0, 0xff, 0]));
        assert!(parse_rgb("#ff88").is_err());
        assert!(parse_rgb("#gg0000").is_err());
        assert!(parse_rgb("#ffé00").is_err());
    }
}
