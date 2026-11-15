//! Finding the pad's raw HID interface (the one VIA and Vial use) through Linux hidraw.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

use crate::protocol::{Frame, REPORT};

/// keyboard.json's USB IDs, as the kernel writes them in uevent.
/// shortcut: pid.codes test PID 1209:0001, private use only; get a real PID before handing boards out.
const HID_ID: &str = "HID_ID=0003:00001209:00000001";
/// The raw HID interface's report descriptor starts with Usage Page 0xFF60, Usage 0x61.
const RAW_DESCRIPTOR: [u8; 5] = [0x06, 0x60, 0xFF, 0x09, 0x61];

/// /dev/hidrawN of the first connected pad, looking in `sysfs` (/sys/class/hidraw).
pub fn find(sysfs: &Path, dev: &Path) -> Option<PathBuf> {
    let mut nodes: Vec<_> = fs::read_dir(sysfs).ok()?.flatten().map(|e| e.path()).filter(|p| is_pad(p)).collect();
    nodes.sort();
    nodes.first().and_then(|p| p.file_name()).map(|name| dev.join(name))
}

fn is_pad(node: &Path) -> bool {
    let uevent = fs::read_to_string(node.join("device/uevent")).unwrap_or_default();
    let descriptor = fs::read(node.join("device/report_descriptor")).unwrap_or_default();
    uevent.lines().any(|l| l == HID_ID) && descriptor.starts_with(&RAW_DESCRIPTOR)
}

/// A reader for the event thread and a writer for the daemon.
pub fn open(path: &Path) -> io::Result<(File, File)> {
    let writer = OpenOptions::new().read(true).write(true).open(path)?;
    Ok((writer.try_clone()?, writer))
}

pub fn write_frame(writer: &mut impl Write, frame: &Frame) -> io::Result<()> {
    // hidraw wants the report id first: 0 on a device without numbered reports
    let mut buf = [0u8; REPORT + 1];
    buf[1..].copy_from_slice(frame);
    writer.write_all(&buf)
}

/// One input report; an error or a zero-length read means the pad is gone.
pub fn read_report(reader: &mut impl Read) -> io::Result<Vec<u8>> {
    let mut buf = [0u8; REPORT];
    match reader.read(&mut buf)? {
        0 => Err(io::ErrorKind::UnexpectedEof.into()),
        n => Ok(buf[..n].to_vec()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fake_node(sysfs: &Path, name: &str, uevent: &str, descriptor: &[u8]) {
        let dir = sysfs.join(name).join("device");
        fs::create_dir_all(&dir).unwrap();
        fs::write(dir.join("uevent"), uevent).unwrap();
        fs::write(dir.join("report_descriptor"), descriptor).unwrap();
    }

    #[test]
    fn finds_only_the_raw_interface_of_our_pad() {
        let sysfs = std::env::temp_dir().join(format!("greyd-sysfs-{}", std::process::id()));
        let _ = fs::remove_dir_all(&sysfs);
        let ours = format!("DRIVER=hid-generic\n{HID_ID}\n");
        fake_node(&sysfs, "hidraw0", &ours, &[0x05, 0x01, 0x09, 0x06]); // our keyboard interface
        fake_node(&sysfs, "hidraw1", "HID_ID=0003:0000FEED:00006060\n", &RAW_DESCRIPTOR); // another VIA board
        assert_eq!(find(&sysfs, Path::new("/dev")), None);
        fake_node(&sysfs, "hidraw2", &ours, &RAW_DESCRIPTOR);
        assert_eq!(find(&sysfs, Path::new("/dev")), Some(PathBuf::from("/dev/hidraw2")));
        fs::remove_dir_all(&sysfs).unwrap();
    }

    #[test]
    fn writes_report_id_then_frame() {
        let mut out = Vec::new();
        write_frame(&mut out, &crate::protocol::heartbeat()).unwrap();
        assert_eq!(out.len(), REPORT + 1);
        assert_eq!(&out[..3], &[0, 0xC7, 0x02]);
    }

    #[test]
    fn empty_read_means_gone() {
        assert!(read_report(&mut &b""[..]).is_err());
        assert_eq!(read_report(&mut &[1u8, 2, 3][..]).unwrap(), vec![1, 2, 3]);
    }
}
