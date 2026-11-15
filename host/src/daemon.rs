//! The running daemon: threads feed one channel (focus, pad reports, control requests),
//! the main loop owns the pad and a 1 s tick (find the pad, heartbeat, config reload).

use std::fs::File;
use std::io::{self, BufRead, BufReader, Write};
use std::os::unix::net::{UnixListener, UnixStream};
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::mpsc::{self, RecvTimeoutError, Sender};
use std::thread;
use std::time::{Duration, Instant, SystemTime};

use serde_json::{json, Value};

use crate::bridge::Bridge;
use crate::config::{self, Config};
use crate::control::{self, Request};
use crate::device;
use crate::focus::{self, Focus};
use crate::protocol::{self as proto, Frame, Incoming};

const TICK: Duration = Duration::from_secs(1);
const FOCUS_RETRY: Duration = Duration::from_secs(5);

macro_rules! log {
    ($($arg:tt)*) => { eprintln!("greyd: {}", format!($($arg)*)) };
}

enum Msg {
    Focus(Focus),
    /// Pad reports carry the connection number, so a stale reader cannot drop a newer link.
    Report(u64, Incoming),
    Gone(u64),
    Control(Request, Sender<Value>),
}

struct Daemon {
    bridge: Bridge,
    pad: Option<(PathBuf, File)>,
    link: u64,
    config_path: PathBuf,
    config_stamp: Option<SystemTime>,
}

pub fn run(config_path: PathBuf) -> io::Result<()> {
    let cfg = config::load(&config_path).unwrap_or_else(|e| {
        log!("{e}; running without app profiles");
        Config::default()
    });
    let (tx, rx) = mpsc::channel();
    start_focus(tx.clone());
    start_control(tx.clone())?;
    let mut d = Daemon { bridge: Bridge::new(cfg), pad: None, link: 0, config_stamp: stamp(&config_path), config_path };
    let mut next_tick = Instant::now();
    loop {
        match rx.recv_timeout(next_tick.saturating_duration_since(Instant::now())) {
            Ok(msg) => d.handle(msg),
            Err(RecvTimeoutError::Timeout) => {
                d.tick(&tx);
                next_tick = Instant::now() + TICK;
            }
            Err(RecvTimeoutError::Disconnected) => unreachable!("run() holds a sender"),
        }
    }
}

fn start_focus(tx: Sender<Msg>) {
    let Some(backend) = focus::Backend::from_env(|name| std::env::var(name).ok()) else {
        log!("none of SWAYSOCK, HYPRLAND_INSTANCE_SIGNATURE, DISPLAY is set: no app profiles");
        return;
    };
    log!("focus from {backend}");
    if let Some(warning) = backend.warning() {
        log!("warning: {warning}");
    }
    thread::spawn(move || loop {
        let err = backend.watch(|f| drop(tx.send(Msg::Focus(f))));
        log!("{backend}: {}; retrying", err.map_or_else(|e| e.to_string(), |()| "closed".into()));
        thread::sleep(FOCUS_RETRY);
    });
}

fn start_control(tx: Sender<Msg>) -> io::Result<()> {
    let path = control::socket_path();
    if UnixStream::connect(&path).is_ok() {
        return Err(io::Error::new(
            io::ErrorKind::AddrInUse,
            format!("{} is taken: greyd already runs", path.display()),
        ));
    }
    let _ = std::fs::remove_file(&path); // stale socket of a greyd that died
    let listener = UnixListener::bind(&path)?;
    log!("control socket {}", path.display());
    thread::spawn(move || {
        for stream in listener.incoming().flatten() {
            if let Err(e) = serve_client(stream, &tx) {
                log!("control client: {e}");
            }
        }
    });
    Ok(())
}

fn serve_client(stream: UnixStream, tx: &Sender<Msg>) -> io::Result<()> {
    let mut line = String::new();
    BufReader::new(&stream).read_line(&mut line)?;
    let reply = match serde_json::from_str::<Request>(&line) {
        Ok(req) => {
            let (reply_tx, reply_rx) = mpsc::channel();
            tx.send(Msg::Control(req, reply_tx)).map_err(io::Error::other)?;
            reply_rx.recv().map_err(io::Error::other)?
        }
        Err(e) => json!({"ok": false, "error": format!("bad request: {e}")}),
    };
    writeln!(&stream, "{reply}")
}

fn stamp(path: &Path) -> Option<SystemTime> {
    std::fs::metadata(path).and_then(|m| m.modified()).ok()
}

/// Run a HOST key's command through /bin/sh, detached, without waiting for it.
fn spawn_shell(cmd: &str) {
    let child = Command::new("/bin/sh")
        .args(["-c", cmd])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .process_group(0)
        .spawn();
    match child {
        Ok(mut c) => drop(thread::spawn(move || c.wait())), // reap it so it does not linger as a zombie
        Err(e) => log!("cannot run {cmd:?}: {e}"),
    }
}

impl Daemon {
    fn handle(&mut self, msg: Msg) {
        match msg {
            Msg::Focus(f) => {
                let frames = self.bridge.focus(f);
                self.send(&frames);
            }
            Msg::Report(link, report) if link == self.link => self.on_report(report),
            Msg::Gone(link) if link == self.link => self.drop_pad("unplugged"),
            Msg::Report(..) | Msg::Gone(_) => {}
            Msg::Control(req, reply) => drop(reply.send(self.on_control(&req))),
        }
    }

    fn on_report(&mut self, report: Incoming) {
        match report {
            Incoming::HostKey { n, pressed: true } => match self.bridge.action(n) {
                Some(cmd) => spawn_shell(&cmd),
                None => log!("HOST_{n}: no action for this app"),
            },
            Incoming::HostKey { .. } => {}
            Incoming::Hello { proto: p, layers, keys } if p == proto::PROTO => {
                log!("pad speaks protocol {p}: {layers} layers, {keys} keys")
            }
            Incoming::Hello { proto: p, .. } => log!("pad speaks protocol {p}, greyd {}: update one", proto::PROTO),
            Incoming::Reply { cmd, status } if status != 0 => log!("pad refused command {cmd:#04x}: status {status}"),
            Incoming::Reply { .. } => {}
        }
    }

    fn on_control(&mut self, req: &Request) -> Value {
        if let Request::State { app, state } = req {
            return match self.bridge.app_state(app, state.clone()) {
                Ok(frames) => {
                    self.send(&frames);
                    json!({"ok": true})
                }
                Err(e) => json!({"ok": false, "error": e}),
            };
        }
        let frame = match control::frame_for(req) {
            Ok(Some(frame)) => frame,
            Ok(None) => {
                let mut status = self.bridge.status();
                status["device"] = json!(self.pad.as_ref().map(|(p, _)| p.display().to_string()));
                return json!({"ok": true, "status": status});
            }
            Err(e) => return json!({"ok": false, "error": e}),
        };
        if self.pad.is_none() {
            return json!({"ok": false, "error": "the pad is not connected"});
        }
        self.send(&[frame]);
        json!({"ok": true})
    }

    fn tick(&mut self, tx: &Sender<Msg>) {
        if self.pad.is_none() {
            self.connect(tx);
        }
        if let Some(beat) = self.bridge.heartbeat() {
            self.send(&[beat]);
        }
        self.reload_if_changed();
    }

    fn connect(&mut self, tx: &Sender<Msg>) {
        let Some(path) = device::find(Path::new("/sys/class/hidraw"), Path::new("/dev")) else { return };
        let (mut reader, writer) = match device::open(&path) {
            Ok(pair) => pair,
            Err(e) => return log!("{}: {e} (udev rule installed? see host/README.md)", path.display()),
        };
        self.link += 1;
        let (link, tx) = (self.link, tx.clone());
        thread::spawn(move || loop {
            match device::read_report(&mut reader) {
                Ok(r) => {
                    if let Some(inc) = proto::parse(&r) {
                        drop(tx.send(Msg::Report(link, inc)));
                    }
                }
                Err(_) => return drop(tx.send(Msg::Gone(link))),
            }
        });
        log!("pad on {}", path.display());
        self.pad = Some((path, writer));
        let frames = self.bridge.connected();
        self.send(&frames);
    }

    fn drop_pad(&mut self, why: &str) {
        if let Some((path, _)) = self.pad.take() {
            log!("pad on {} {why}", path.display());
        }
        self.link += 1;
        self.bridge.disconnected();
    }

    fn send(&mut self, frames: &[Frame]) {
        let Some((_, writer)) = self.pad.as_mut() else { return };
        if let Some(e) = frames.iter().find_map(|f| device::write_frame(writer, f).err()) {
            self.drop_pad(&format!("failed: {e}"));
        }
    }

    fn reload_if_changed(&mut self) {
        let now = stamp(&self.config_path);
        if now == self.config_stamp {
            return;
        }
        self.config_stamp = now;
        match config::load(&self.config_path) {
            Ok(cfg) => {
                log!("reloaded {}", self.config_path.display());
                let frames = self.bridge.reload(cfg);
                self.send(&frames);
            }
            Err(e) => log!("{e}; keeping the previous config"),
        }
    }
}
