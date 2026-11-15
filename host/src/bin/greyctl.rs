//! greyctl: raise alerts, colour keys and report app states to the greycode pad through greyd.

use std::process::ExitCode;

use serde_json::{json, Value};

const USAGE: &str = "usage:
  greyctl status
  greyctl alert info|ok|warn|error TEXT [--timeout SECONDS] [--color #rrggbb] [--solid|--pulse|--blink]
  greyctl clear
  greyctl keys 0,1,2 #rrggbb|off
  greyctl state APP STATE|--clear";

fn alert(args: &[String]) -> Result<Value, String> {
    let [level, text, opts @ ..] = args else { return Err("alert needs a level and a text".into()) };
    let mut req = json!({"cmd": "alert", "level": level, "text": text});
    let mut opts = opts.iter();
    while let Some(opt) = opts.next() {
        let mut value = || opts.next().ok_or(format!("{opt} needs a value"));
        match opt.as_str() {
            "--timeout" => req["timeout"] = json!(value()?.parse::<u16>().map_err(|e| format!("--timeout: {e}"))?),
            "--color" => req["color"] = json!(value()?),
            "--solid" | "--pulse" | "--blink" => req["pattern"] = json!(&opt[2..]),
            _ => return Err(format!("unknown option {opt}")),
        }
    }
    Ok(req)
}

fn keys(args: &[String]) -> Result<Value, String> {
    let [list, color] = args else { return Err("keys needs a key list and a colour".into()) };
    let keys = list.split(',').map(|k| k.trim().parse::<u8>().map_err(|e| format!("key {k:?}: {e}")));
    let keys = keys.collect::<Result<Vec<_>, _>>()?;
    let color = (color != "off").then_some(color);
    Ok(json!({"cmd": "keys", "keys": keys, "color": color}))
}

fn state(args: &[String]) -> Result<Value, String> {
    let [app, state] = args else { return Err("state needs an app and a state (or --clear)".into()) };
    let state = (state != "--clear").then_some(state);
    Ok(json!({"cmd": "state", "app": app, "state": state}))
}

fn request(args: &[String]) -> Result<Value, String> {
    match args.split_first() {
        Some((cmd, [])) if cmd == "status" || cmd == "clear" => Ok(json!({"cmd": cmd})),
        Some((cmd, rest)) if cmd == "alert" => alert(rest),
        Some((cmd, rest)) if cmd == "keys" => keys(rest),
        Some((cmd, rest)) if cmd == "state" => state(rest),
        _ => Err(USAGE.into()),
    }
}

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let reply = request(&args).and_then(|req| greyd::control::call(&req).map_err(|e| e.to_string()));
    match reply {
        Ok(r) if r["ok"] == true => {
            if let Some(status) = r.get("status") {
                println!("{}", serde_json::to_string_pretty(status).unwrap_or_default());
            }
            ExitCode::SUCCESS
        }
        Ok(r) => {
            eprintln!("greyctl: {}", r["error"].as_str().unwrap_or("greyd refused the request"));
            ExitCode::FAILURE
        }
        Err(e) => {
            eprintln!("greyctl: {e}");
            ExitCode::FAILURE
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn args(line: &str) -> Vec<String> {
        line.split(' ').map(str::to_string).collect()
    }

    #[test]
    fn state_requests() {
        let set = request(&args("state freecad Sketcher")).unwrap();
        assert_eq!(set, json!({"cmd": "state", "app": "freecad", "state": "Sketcher"}));
        let cleared = request(&args("state freecad --clear")).unwrap();
        assert_eq!(cleared, json!({"cmd": "state", "app": "freecad", "state": null}));
        assert!(request(&args("state freecad")).unwrap_err().contains("--clear"));
    }
}
