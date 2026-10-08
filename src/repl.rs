//! The `pman>` prompt (`pman --repl`): a small line editor with history and tab completion, for
//! hosts that give pman a terminal but no shell (the phone).

use crossterm::{
    cursor,
    event::{self, Event, KeyCode, KeyEventKind, KeyModifiers},
    queue,
    style::Print,
    terminal::{self, ClearType},
};
use std::fs;
use std::io::{self, Write};
use std::path::PathBuf;

const HISTORY_MAX: usize = 500;

pub struct History {
    lines: Vec<String>,
    path: PathBuf,
}

impl History {
    pub fn load() -> History {
        let path = crate::pack::data_dir().join("history");
        let lines = fs::read_to_string(&path).map(|t| t.lines().map(String::from).collect()).unwrap_or_default();
        History { lines, path }
    }

    pub fn add(&mut self, line: &str) {
        if line.trim().is_empty() || self.lines.last().map_or(false, |l| l == line) {
            return;
        }
        self.lines.push(line.to_string());
        if self.lines.len() > HISTORY_MAX {
            self.lines.remove(0);
        }
        if let Some(d) = self.path.parent() {
            let _ = fs::create_dir_all(d);
        }
        let _ = fs::write(&self.path, self.lines.join("\n") + "\n");
    }
}

/// Completion candidates for the word that ends at the cursor: (start of that word, matches).
pub type Completer<'a> = &'a dyn Fn(&str) -> (usize, Vec<String>);

struct RawGuard;

impl RawGuard {
    fn new() -> io::Result<RawGuard> {
        terminal::enable_raw_mode()?;
        Ok(RawGuard)
    }
}

impl Drop for RawGuard {
    fn drop(&mut self) {
        let _ = terminal::disable_raw_mode();
    }
}

fn common_prefix(items: &[String]) -> String {
    let mut p: Vec<char> = items[0].chars().collect();
    for s in &items[1..] {
        let n = p.iter().zip(s.chars()).take_while(|(a, b)| **a == *b).count();
        p.truncate(n);
    }
    p.into_iter().collect()
}

fn redraw(out: &mut io::Stdout, prompt: &str, buf: &[char], pos: usize) -> io::Result<()> {
    let line: String = buf.iter().collect();
    queue!(out, Print("\r"), terminal::Clear(ClearType::UntilNewLine), Print(prompt), Print(&line))?;
    let col = prompt.chars().count() + pos;
    queue!(out, Print("\r"))?;
    if col > 0 {
        queue!(out, cursor::MoveRight(col as u16))?;
    }
    out.flush()
}

/// Reads one edited line; `None` at end of input (Ctrl-D on an empty line).
pub fn read_line(prompt: &str, history: &History, complete: Completer) -> io::Result<Option<String>> {
    let _guard = RawGuard::new()?;
    let mut out = io::stdout();
    let mut buf: Vec<char> = Vec::new();
    let mut pos = 0usize;
    let mut hist_at = history.lines.len();
    let mut stash: Vec<char> = Vec::new();
    redraw(&mut out, prompt, &buf, pos)?;
    loop {
        let Event::Key(k) = event::read()? else {
            redraw(&mut out, prompt, &buf, pos)?; // resized
            continue;
        };
        if k.kind == KeyEventKind::Release {
            continue;
        }
        let ctrl = k.modifiers.contains(KeyModifiers::CONTROL);
        match k.code {
            KeyCode::Enter => {
                queue!(out, Print("\r\n"))?;
                out.flush()?;
                return Ok(Some(buf.iter().collect()));
            }
            KeyCode::Char('d') if ctrl => {
                if buf.is_empty() {
                    queue!(out, Print("\r\n"))?;
                    out.flush()?;
                    return Ok(None);
                }
                if pos < buf.len() {
                    buf.remove(pos);
                }
            }
            KeyCode::Char('c') if ctrl => {
                queue!(out, Print("^C\r\n"))?;
                buf.clear();
                pos = 0;
            }
            KeyCode::Char('a') if ctrl => pos = 0,
            KeyCode::Char('e') if ctrl => pos = buf.len(),
            KeyCode::Char('u') if ctrl => {
                buf.drain(..pos);
                pos = 0;
            }
            KeyCode::Char('k') if ctrl => buf.truncate(pos),
            KeyCode::Char('w') if ctrl => {
                let mut i = pos;
                while i > 0 && buf[i - 1] == ' ' {
                    i -= 1;
                }
                while i > 0 && buf[i - 1] != ' ' {
                    i -= 1;
                }
                buf.drain(i..pos);
                pos = i;
            }
            KeyCode::Char('l') if ctrl => {
                queue!(out, terminal::Clear(ClearType::All), cursor::MoveTo(0, 0))?;
            }
            KeyCode::Char(c) if !ctrl => {
                buf.insert(pos, c);
                pos += 1;
            }
            KeyCode::Backspace => {
                if pos > 0 {
                    pos -= 1;
                    buf.remove(pos);
                }
            }
            KeyCode::Delete => {
                if pos < buf.len() {
                    buf.remove(pos);
                }
            }
            KeyCode::Left => pos = pos.saturating_sub(1),
            KeyCode::Right => pos = (pos + 1).min(buf.len()),
            KeyCode::Home => pos = 0,
            KeyCode::End => pos = buf.len(),
            KeyCode::Up => {
                if hist_at > 0 {
                    if hist_at == history.lines.len() {
                        stash = buf.clone();
                    }
                    hist_at -= 1;
                    buf = history.lines[hist_at].chars().collect();
                    pos = buf.len();
                }
            }
            KeyCode::Down => {
                if hist_at < history.lines.len() {
                    hist_at += 1;
                    buf = if hist_at == history.lines.len() { stash.clone() } else { history.lines[hist_at].chars().collect() };
                    pos = buf.len();
                }
            }
            KeyCode::Tab => {
                let before: String = buf[..pos].iter().collect();
                let (start, found) = complete(&before);
                match found.len() {
                    0 => {}
                    1 => {
                        let word: Vec<char> = found[0].chars().collect();
                        let n = word.len();
                        buf.splice(start..pos, word);
                        pos = start + n;
                        if buf.get(pos) != Some(&' ') {
                            buf.insert(pos, ' ');
                        }
                        pos += 1;
                    }
                    _ => {
                        let cp: Vec<char> = common_prefix(&found).chars().collect();
                        if cp.len() > pos - start {
                            let n = cp.len();
                            buf.splice(start..pos, cp);
                            pos = start + n;
                        } else {
                            // nothing more to add: list the candidates under the prompt
                            let width = terminal::size().map(|s| s.0 as usize).unwrap_or(80);
                            let cell = found.iter().map(|s| s.chars().count()).max().unwrap_or(1) + 2;
                            let per = (width / cell).max(1);
                            queue!(out, Print("\r\n"))?;
                            for (i, f) in found.iter().take(60).enumerate() {
                                queue!(out, Print(format!("{f:<cell$}")))?;
                                if (i + 1) % per == 0 {
                                    queue!(out, Print("\r\n"))?;
                                }
                            }
                            if found.len() > 60 {
                                queue!(out, Print(format!("… {} more", found.len() - 60)))?;
                            }
                            queue!(out, Print("\r\n"))?;
                        }
                    }
                }
            }
            _ => {}
        }
        redraw(&mut out, prompt, &buf, pos)?;
    }
}
