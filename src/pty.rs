//! `pman --pty-host COLS ROWS [args...]`: runs pman itself on a pseudo terminal and relays it over
//! stdin/stdout, for hosts that cannot create a pty themselves (the Android app).
//!
//! Host stdin carries frames: a type byte (0 = keyboard bytes, 1 = resize), a big-endian u16 length,
//! then the payload (resize: cols u16, rows u16 big-endian). Host stdout is the raw terminal output.

use std::fs::File;
use std::io::{Read, Write};
use std::os::unix::io::FromRawFd;
use std::os::unix::process::CommandExt;
use std::process::Command;

fn set_size(fd: libc::c_int, cols: u16, rows: u16) {
    let ws = libc::winsize { ws_row: rows, ws_col: cols, ws_xpixel: 0, ws_ypixel: 0 };
    unsafe {
        libc::ioctl(fd, libc::TIOCSWINSZ as _, &ws);
    }
}

/// Runs the child to completion and returns its exit code.
pub fn host(cols: u16, rows: u16, args: &[String]) -> i32 {
    let ws = libc::winsize { ws_row: rows, ws_col: cols, ws_xpixel: 0, ws_ypixel: 0 };
    let mut master: libc::c_int = 0;
    let pid = unsafe { libc::forkpty(&mut master, std::ptr::null_mut(), std::ptr::null_mut(), &ws as *const _ as *mut _) };
    if pid < 0 {
        eprintln!("pman: cannot open a pty");
        return 1;
    }
    if pid == 0 {
        let exe = std::env::current_exe().unwrap_or_else(|_| "pman".into());
        let err = Command::new(exe).args(args).env("TERM", "xterm-256color").exec();
        eprintln!("pman: cannot start: {err}");
        unsafe { libc::_exit(127) };
    }

    // keyboard and resize frames from the host go to the pty
    let wfd = unsafe { libc::dup(master) };
    std::thread::spawn(move || {
        let mut input = std::io::stdin().lock();
        let mut w = unsafe { File::from_raw_fd(wfd) };
        let mut head = [0u8; 3];
        while input.read_exact(&mut head).is_ok() {
            let mut payload = vec![0u8; u16::from_be_bytes([head[1], head[2]]) as usize];
            if input.read_exact(&mut payload).is_err() {
                break;
            }
            match head[0] {
                0 => {
                    if w.write_all(&payload).is_err() {
                        break;
                    }
                }
                1 if payload.len() == 4 => {
                    set_size(wfd, u16::from_be_bytes([payload[0], payload[1]]), u16::from_be_bytes([payload[2], payload[3]]));
                }
                _ => {}
            }
        }
        // host went away: hang up the child
        unsafe { libc::kill(pid, libc::SIGHUP) };
    });

    // terminal output goes to the host
    let mut r = unsafe { File::from_raw_fd(master) };
    let mut out = std::io::stdout().lock();
    let mut buf = [0u8; 8192];
    loop {
        match r.read(&mut buf) {
            Ok(0) | Err(_) => break, // EIO once the child has exited
            Ok(n) => {
                if out.write_all(&buf[..n]).is_err() || out.flush().is_err() {
                    break;
                }
            }
        }
    }
    let mut status: libc::c_int = 0;
    unsafe { libc::waitpid(pid, &mut status, 0) };
    if libc::WIFEXITED(status) {
        libc::WEXITSTATUS(status)
    } else {
        1
    }
}
