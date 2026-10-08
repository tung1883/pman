//! Talking to a host application that embeds pman (the Android app). The host starts pman with
//! `PMAN_HOST` set; pman asks it for things it cannot do itself by printing a private escape
//! sequence, `ESC ] 7770 ; <command> BEL`, which the host's terminal view picks up:
//!
//!   install <pack id>      download and install a doc pack; the host types back `ok` or `err <why>` + Enter
//!   insert <base64 text>   put the text in the host's editor (and close the terminal)

use crossterm::event::{self, Event, KeyCode, KeyEventKind, KeyModifiers};
use crossterm::terminal;
use std::io::{self, Write};

pub fn active() -> bool {
    std::env::var_os("PMAN_HOST").is_some()
}

pub fn emit(cmd: &str) {
    let mut out = io::stdout();
    let _ = write!(out, "\x1b]7770;{cmd}\x07");
    let _ = out.flush();
}

/// Sends `cmd` and waits for the host's one-line reply (typed back without echo).
#[cfg_attr(feature = "net", allow(dead_code))]
pub fn request(cmd: &str) -> Result<(), String> {
    if !active() {
        return Err("this build cannot download; install packs from a computer or the host app".into());
    }
    emit(cmd);
    terminal::enable_raw_mode().map_err(|e| e.to_string())?;
    let mut line = String::new();
    let outcome = loop {
        match event::read() {
            Ok(Event::Key(k)) if k.kind != KeyEventKind::Release => match k.code {
                KeyCode::Enter => break Ok(()),
                KeyCode::Char('c') if k.modifiers.contains(KeyModifiers::CONTROL) => break Err("cancelled".to_string()),
                KeyCode::Char(c) => line.push(c),
                _ => {}
            },
            Ok(_) => {}
            Err(e) => break Err(e.to_string()),
        }
    };
    let _ = terminal::disable_raw_mode();
    outcome?;
    match line.trim() {
        "ok" => Ok(()),
        other => Err(other.strip_prefix("err").unwrap_or(other).trim().to_string()),
    }
}

pub fn base64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len() * 4 / 3 + 4);
    for chunk in data.chunks(3) {
        let n = (chunk[0] as u32) << 16 | (*chunk.get(1).unwrap_or(&0) as u32) << 8 | *chunk.get(2).unwrap_or(&0) as u32;
        out.push(T[(n >> 18) as usize & 63] as char);
        out.push(T[(n >> 12) as usize & 63] as char);
        out.push(if chunk.len() > 1 { T[(n >> 6) as usize & 63] as char } else { '=' });
        out.push(if chunk.len() > 2 { T[n as usize & 63] as char } else { '=' });
    }
    out
}
