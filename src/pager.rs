//! A small `less`-style pager: wrapped text, section headings, `/` search with highlights,
//! `n`/`N`, a section list (`t`), and paging keys. Works on Windows, Linux, macOS and Android.

use crate::index::Page;
use crossterm::{
    cursor, event::{self, Event, KeyCode, KeyEvent, KeyEventKind, KeyModifiers},
    execute, queue,
    style::{Attribute, Color, Print, ResetColor, SetAttribute, SetBackgroundColor, SetForegroundColor},
    terminal::{self, ClearType},
};
use std::io::{self, Write};

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Normal,
    Heading,
    Dim,
}

struct Row {
    text: String,
    line: usize,
    kind: Kind,
}

enum Mode {
    Normal,
    Search(String),
    Toc(usize),
}

struct Pager<'a> {
    page: &'a Page,
    rows: Vec<Row>,
    row_of_line: Vec<usize>,
    top: usize,
    width: usize,
    height: usize,
    terms: Vec<String>,
    /// (row, start char, length in chars)
    matches: Vec<(usize, usize, usize)>,
    current: Option<usize>,
    mode: Mode,
    note: String,
}

struct RawGuard;

impl RawGuard {
    fn new() -> io::Result<RawGuard> {
        terminal::enable_raw_mode()?;
        execute!(io::stdout(), terminal::EnterAlternateScreen, cursor::Hide)?;
        Ok(RawGuard)
    }
}

impl Drop for RawGuard {
    fn drop(&mut self) {
        let _ = execute!(io::stdout(), cursor::Show, terminal::LeaveAlternateScreen);
        let _ = terminal::disable_raw_mode();
    }
}

pub fn run(page: &Page, start_line: usize, terms: Vec<String>) -> io::Result<()> {
    let _guard = RawGuard::new()?;
    let (w, h) = terminal::size()?;
    let mut p = Pager {
        page,
        rows: Vec::new(),
        row_of_line: Vec::new(),
        top: 0,
        width: w as usize,
        height: h as usize,
        terms,
        matches: Vec::new(),
        current: None,
        mode: Mode::Normal,
        note: String::new(),
    };
    p.layout();
    p.top = p.row_of_line.get(start_line).copied().unwrap_or(0);
    p.find_matches();
    if !p.matches.is_empty() {
        p.current = p.matches.iter().position(|m| m.0 >= p.top).or(Some(0));
    }
    p.clamp();
    loop {
        p.draw()?;
        match event::read()? {
            Event::Resize(w, h) => {
                let line = p.rows.get(p.top).map_or(0, |r| r.line);
                p.width = w as usize;
                p.height = h as usize;
                p.layout();
                p.top = p.row_of_line.get(line).copied().unwrap_or(0);
                p.find_matches();
                p.clamp();
            }
            Event::Key(k) if k.kind != KeyEventKind::Release => {
                if p.key(k) {
                    return Ok(());
                }
            }
            _ => {}
        }
    }
}

impl<'a> Pager<'a> {
    fn body_height(&self) -> usize {
        self.height.saturating_sub(1).max(1)
    }

    fn layout(&mut self) {
        let width = self.width.max(20);
        self.rows.clear();
        self.row_of_line.clear();
        let headings: Vec<usize> = self.page.sections().iter().map(|s| s.line).collect();
        for (i, line) in self.page.lines().iter().enumerate() {
            self.row_of_line.push(self.rows.len());
            let kind = if headings.contains(&i) {
                Kind::Heading
            } else if i == 0 {
                Kind::Dim
            } else {
                Kind::Normal
            };
            for piece in wrap(line, width - 1) {
                self.rows.push(Row { text: piece, line: i, kind });
            }
        }
    }

    fn clamp(&mut self) {
        let max = self.rows.len().saturating_sub(self.body_height());
        if self.top > max {
            self.top = max;
        }
    }

    fn find_matches(&mut self) {
        self.matches.clear();
        for (ri, row) in self.rows.iter().enumerate() {
            let chars: Vec<char> = row.text.to_lowercase().chars().collect();
            for t in &self.terms {
                let needle: Vec<char> = t.chars().collect();
                if needle.is_empty() || chars.len() < needle.len() {
                    continue;
                }
                let mut i = 0;
                while i + needle.len() <= chars.len() {
                    if chars[i..i + needle.len()] == needle[..] {
                        self.matches.push((ri, i, needle.len()));
                        i += needle.len();
                    } else {
                        i += 1;
                    }
                }
            }
        }
        self.matches.sort();
        self.current = None;
    }

    fn goto_match(&mut self, idx: usize) {
        self.current = Some(idx);
        let row = self.matches[idx].0;
        let third = self.body_height() / 3;
        self.top = row.saturating_sub(third);
        self.clamp();
    }

    fn search(&mut self, q: &str) {
        let q = q.trim().to_lowercase();
        if q.is_empty() {
            return;
        }
        self.terms = vec![q.clone()];
        self.find_matches();
        if self.matches.is_empty() {
            self.note = format!("pattern not found: {q}");
            return;
        }
        let from = self.top + 1;
        let idx = self.matches.iter().position(|m| m.0 >= from).unwrap_or(0);
        self.goto_match(idx);
    }

    fn step_match(&mut self, forward: bool) {
        if self.matches.is_empty() {
            self.note = "no search pattern (use /word)".into();
            return;
        }
        let n = self.matches.len();
        let cur = self.current.unwrap_or(if forward { n - 1 } else { 0 });
        let next = if forward { (cur + 1) % n } else { (cur + n - 1) % n };
        self.goto_match(next);
    }

    /// Returns true to quit.
    fn key(&mut self, k: KeyEvent) -> bool {
        self.note.clear();
        let ctrl = k.modifiers.contains(KeyModifiers::CONTROL);
        match &mut self.mode {
            Mode::Search(buf) => {
                match k.code {
                    KeyCode::Esc => self.mode = Mode::Normal,
                    KeyCode::Enter => {
                        let q = std::mem::take(buf);
                        self.mode = Mode::Normal;
                        self.search(&q);
                    }
                    KeyCode::Backspace => {
                        if buf.pop().is_none() {
                            self.mode = Mode::Normal;
                        }
                    }
                    KeyCode::Char(c) if !ctrl => buf.push(c),
                    _ => {}
                }
                return false;
            }
            Mode::Toc(sel) => {
                let n = self.page.sections().len();
                match k.code {
                    KeyCode::Esc | KeyCode::Char('q') | KeyCode::Char('t') => self.mode = Mode::Normal,
                    KeyCode::Down | KeyCode::Char('j') => *sel = (*sel + 1).min(n - 1),
                    KeyCode::Up | KeyCode::Char('k') => *sel = sel.saturating_sub(1),
                    KeyCode::Home | KeyCode::Char('g') => *sel = 0,
                    KeyCode::End | KeyCode::Char('G') => *sel = n - 1,
                    KeyCode::Enter => {
                        let line = self.page.sections()[*sel].line;
                        self.mode = Mode::Normal;
                        self.top = self.row_of_line.get(line).copied().unwrap_or(0);
                        self.clamp();
                    }
                    _ => {}
                }
                return false;
            }
            Mode::Normal => {}
        }
        let page = self.body_height();
        let max = self.rows.len().saturating_sub(page);
        match k.code {
            KeyCode::Char('q') | KeyCode::Esc => return true,
            KeyCode::Char('c') if ctrl => return true,
            KeyCode::Down | KeyCode::Char('j') | KeyCode::Enter => self.top = (self.top + 1).min(max),
            KeyCode::Up | KeyCode::Char('k') => self.top = self.top.saturating_sub(1),
            KeyCode::PageDown | KeyCode::Char(' ') | KeyCode::Char('f') => self.top = (self.top + page.saturating_sub(1)).min(max),
            KeyCode::PageUp | KeyCode::Char('b') => self.top = self.top.saturating_sub(page.saturating_sub(1)),
            KeyCode::Char('d') => self.top = (self.top + page / 2).min(max),
            KeyCode::Char('u') => self.top = self.top.saturating_sub(page / 2),
            KeyCode::Home | KeyCode::Char('g') => self.top = 0,
            KeyCode::End | KeyCode::Char('G') => self.top = max,
            KeyCode::Char('/') => self.mode = Mode::Search(String::new()),
            KeyCode::Char('n') => self.step_match(true),
            KeyCode::Char('N') => self.step_match(false),
            KeyCode::Char('t') => {
                let line = self.rows.get(self.top).map_or(0, |r| r.line);
                self.mode = Mode::Toc(self.page.section_at(line));
            }
            KeyCode::Char('?') => {
                self.note = "j/k line  space/b page  d/u half  g/G ends  / search  n/N next/prev  t sections  q quit".into();
            }
            _ => {}
        }
        false
    }

    fn draw(&self) -> io::Result<()> {
        let mut out = io::stdout();
        queue!(out, cursor::MoveTo(0, 0), terminal::Clear(ClearType::All))?;
        let body = self.body_height();
        if let Mode::Toc(sel) = self.mode {
            self.draw_toc(&mut out, sel, body)?;
        } else {
            for y in 0..body {
                let ri = self.top + y;
                let Some(row) = self.rows.get(ri) else { break };
                queue!(out, cursor::MoveTo(0, y as u16))?;
                self.draw_row(&mut out, ri, row)?;
            }
        }
        // bottom line
        queue!(out, cursor::MoveTo(0, (self.height - 1) as u16))?;
        match &self.mode {
            Mode::Search(buf) => {
                queue!(out, Print(format!("/{buf}")), cursor::Show)?;
            }
            _ => {
                let status = self.status();
                let mut s: String = status.chars().take(self.width.saturating_sub(1)).collect();
                while s.chars().count() < self.width.saturating_sub(1) {
                    s.push(' ');
                }
                queue!(out, cursor::Hide, SetAttribute(Attribute::Reverse), Print(s), SetAttribute(Attribute::Reset))?;
            }
        }
        out.flush()
    }

    fn draw_toc(&self, out: &mut io::Stdout, sel: usize, body: usize) -> io::Result<()> {
        let n = self.page.sections().len();
        let start = if sel >= body { sel + 1 - body } else { 0 };
        for y in 0..body {
            let i = start + y;
            if i >= n {
                break;
            }
            queue!(out, cursor::MoveTo(0, y as u16))?;
            let title: String = self.page.sections()[i].title.chars().take(self.width.saturating_sub(5)).collect();
            if i == sel {
                queue!(out, SetAttribute(Attribute::Reverse), Print(format!(" {:>3} {title}", i + 1)), SetAttribute(Attribute::Reset))?;
            } else {
                queue!(out, Print(format!(" {:>3} {title}", i + 1)))?;
            }
        }
        Ok(())
    }

    fn draw_row(&self, out: &mut io::Stdout, ri: usize, row: &Row) -> io::Result<()> {
        let chars: Vec<char> = row.text.chars().collect();
        // highlight ranges on this row
        let mut hl: Vec<(usize, usize, bool)> = Vec::new();
        let lo = self.matches.partition_point(|m| m.0 < ri);
        for (idx, m) in self.matches.iter().enumerate().skip(lo) {
            if m.0 != ri {
                break;
            }
            hl.push((m.1, m.1 + m.2, self.current == Some(idx)));
        }
        match row.kind {
            Kind::Heading => queue!(out, SetAttribute(Attribute::Bold), SetForegroundColor(Color::Yellow))?,
            Kind::Dim => queue!(out, SetForegroundColor(Color::DarkGrey))?,
            Kind::Normal => {}
        }
        let mut i = 0;
        while i < chars.len() {
            if let Some(&(s, e, cur)) = hl.iter().find(|h| h.0 <= i && i < h.1) {
                let end = e.min(chars.len());
                let seg: String = chars[i..end].iter().collect();
                let (bg, fg) = if cur { (Color::Yellow, Color::Black) } else { (Color::DarkYellow, Color::Black) };
                queue!(out, SetBackgroundColor(bg), SetForegroundColor(fg), Print(seg), ResetColor)?;
                match row.kind {
                    Kind::Heading => queue!(out, SetAttribute(Attribute::Bold), SetForegroundColor(Color::Yellow))?,
                    Kind::Dim => queue!(out, SetForegroundColor(Color::DarkGrey))?,
                    Kind::Normal => {}
                }
                let _ = s;
                i = end;
            } else {
                let next = hl.iter().filter(|h| h.0 > i).map(|h| h.0).min().unwrap_or(chars.len());
                let seg: String = chars[i..next].iter().collect();
                queue!(out, Print(seg))?;
                i = next;
            }
        }
        queue!(out, SetAttribute(Attribute::Reset), ResetColor)?;
        Ok(())
    }

    fn status(&self) -> String {
        if !self.note.is_empty() {
            return self.note.clone();
        }
        if let Mode::Toc(_) = self.mode {
            return format!("{} · sections · enter jump  q back", self.page.id);
        }
        let line = self.rows.get(self.top).map_or(0, |r| r.line);
        let sec = &self.page.sections()[self.page.section_at(line)].title;
        let max = self.rows.len().saturating_sub(self.body_height()).max(1);
        let pct = (self.top * 100 / max).min(100);
        let mut s = format!("{} · {} · {pct}%", self.page.id, sec.to_lowercase());
        if !self.matches.is_empty() {
            let c = self.current.map_or("-".to_string(), |c| (c + 1).to_string());
            s.push_str(&format!(" · match {c}/{}", self.matches.len()));
        }
        s.push_str("  (? help)");
        s
    }
}

/// Word-wraps `text` to `width` chars, keeping a leading indent on continuation lines of
/// verbatim/bullet lines.
fn wrap(text: &str, width: usize) -> Vec<String> {
    let chars: Vec<char> = text.chars().collect();
    if chars.len() <= width {
        return vec![text.to_string()];
    }
    let indent = chars.iter().take_while(|&&c| c == ' ').count();
    let hang = if text.trim_start().starts_with("* ") || text.trim_start().starts_with("> ") { indent + 2 } else { indent };
    let hang = hang.min(width / 2);
    let mut out = Vec::new();
    let mut start = 0;
    let mut first = true;
    while start < chars.len() {
        let pad = if first { 0 } else { hang };
        let room = width - pad;
        if chars.len() - start <= room {
            out.push(format!("{}{}", " ".repeat(pad), chars[start..].iter().collect::<String>()));
            break;
        }
        let mut cut = start + room;
        // break at the last space within the window
        if let Some(sp) = chars[start..cut].iter().rposition(|&c| c == ' ') {
            if sp > 0 {
                cut = start + sp;
            }
        }
        let seg: String = chars[start..cut].iter().collect();
        out.push(format!("{}{}", " ".repeat(pad), seg.trim_end()));
        start = cut;
        while start < chars.len() && chars[start] == ' ' {
            start += 1;
        }
        first = false;
    }
    out
}

/// Interactive list of `(id, description)` items with type-to-filter. Enter returns the chosen item's
/// index in `items`; Esc/Ctrl-C returns `None`. `filter` and `selected` carry over between calls so the
/// list looks the same when the user comes back from reading a page.
pub fn pick(title: &str, items: &[(String, String)], filter: &mut String, selected: &mut usize) -> io::Result<Option<usize>> {
    let _guard = RawGuard::new()?;
    let (mut w, mut h) = terminal::size()?;
    let mut cursor_pos = 0usize; // index into the filtered list
    let mut top = 0usize;
    let mut first = true;
    loop {
        let shown = filtered(items, filter);
        if first {
            cursor_pos = shown.iter().position(|&i| i == *selected).unwrap_or(0);
            first = false;
        }
        if cursor_pos >= shown.len() {
            cursor_pos = shown.len().saturating_sub(1);
        }
        let rows = (h as usize).saturating_sub(3).max(1);
        if cursor_pos < top {
            top = cursor_pos;
        }
        if cursor_pos >= top + rows {
            top = cursor_pos + 1 - rows;
        }
        draw_pick(title, items, &shown, filter, cursor_pos, top, w as usize, h as usize)?;
        match event::read()? {
            Event::Resize(nw, nh) => {
                w = nw;
                h = nh;
            }
            Event::Key(k) if k.kind != KeyEventKind::Release => {
                let ctrl = k.modifiers.contains(KeyModifiers::CONTROL);
                match k.code {
                    KeyCode::Esc => return Ok(None),
                    KeyCode::Char('c') if ctrl => return Ok(None),
                    KeyCode::Enter => {
                        if let Some(&i) = shown.get(cursor_pos) {
                            *selected = i;
                            return Ok(Some(i));
                        }
                    }
                    KeyCode::Down => cursor_pos = (cursor_pos + 1).min(shown.len().saturating_sub(1)),
                    KeyCode::Up => cursor_pos = cursor_pos.saturating_sub(1),
                    KeyCode::PageDown => cursor_pos = (cursor_pos + rows).min(shown.len().saturating_sub(1)),
                    KeyCode::PageUp => cursor_pos = cursor_pos.saturating_sub(rows),
                    KeyCode::Home => cursor_pos = 0,
                    KeyCode::End => cursor_pos = shown.len().saturating_sub(1),
                    KeyCode::Backspace => {
                        filter.pop();
                        cursor_pos = 0;
                        top = 0;
                    }
                    KeyCode::Char('u') if ctrl => {
                        filter.clear();
                        cursor_pos = 0;
                        top = 0;
                    }
                    KeyCode::Char(c) if !ctrl => {
                        filter.push(c);
                        cursor_pos = 0;
                        top = 0;
                    }
                    _ => {}
                }
            }
            _ => {}
        }
    }
}

/// Indexes of the items matching every word of `filter`; names that start with the first word come first.
fn filtered(items: &[(String, String)], filter: &str) -> Vec<usize> {
    let words: Vec<String> = filter.to_lowercase().split_whitespace().map(String::from).collect();
    let mut out: Vec<(bool, usize)> = Vec::new();
    for (i, (id, desc)) in items.iter().enumerate() {
        let hay = format!("{id} {desc}").to_lowercase();
        if words.iter().all(|w| hay.contains(w.as_str())) {
            let name = id.split_once('.').map_or(id.as_str(), |(_, n)| n).to_lowercase();
            let prefix = words.first().map_or(true, |w| name.starts_with(w.as_str()));
            out.push((!prefix, i));
        }
    }
    out.sort();
    out.into_iter().map(|(_, i)| i).collect()
}

#[allow(clippy::too_many_arguments)]
fn draw_pick(title: &str, items: &[(String, String)], shown: &[usize], filter: &str, cur: usize, top: usize, w: usize, h: usize) -> io::Result<()> {
    let mut out = io::stdout();
    queue!(out, cursor::Hide, cursor::MoveTo(0, 0), terminal::Clear(ClearType::All))?;
    queue!(out, SetAttribute(Attribute::Bold), SetForegroundColor(Color::Yellow), Print(clip(title, w)), SetAttribute(Attribute::Reset), ResetColor)?;
    queue!(out, cursor::MoveTo(0, 1), Print(format!("filter: {filter}")))?;
    let rows = h.saturating_sub(3).max(1);
    // one id column for the whole list: as wide as the longest id, but never more than ~45% of the screen
    let col = items.iter().map(|(id, _)| id.chars().count()).max().unwrap_or(10).min(w * 45 / 100).max(8);
    for y in 0..rows {
        let Some(&i) = shown.get(top + y) else { break };
        let (id, desc) = &items[i];
        let id: String = if id.chars().count() > col {
            id.chars().take(col - 1).chain(std::iter::once('…')).collect()
        } else {
            id.clone()
        };
        let line = clip(&format!(" {id:<col$} {desc}"), w);
        queue!(out, cursor::MoveTo(0, (y + 2) as u16))?;
        if top + y == cur {
            queue!(out, SetAttribute(Attribute::Reverse), Print(pad(&line, w)), SetAttribute(Attribute::Reset))?;
        } else {
            queue!(out, Print(line))?;
        }
    }
    let status = format!(" {} of {}   type to filter   up/down move   Enter open   Esc quit", shown.len(), items.len());
    queue!(out, cursor::MoveTo(0, (h - 1) as u16), SetAttribute(Attribute::Reverse), Print(pad(&clip(&status, w), w)), SetAttribute(Attribute::Reset))?;
    // show the text cursor after the filter text
    let cx = ("filter: ".len() + filter.chars().count()).min(w.saturating_sub(1));
    queue!(out, cursor::MoveTo(cx as u16, 1), cursor::Show)?;
    out.flush()
}

fn clip(s: &str, w: usize) -> String {
    s.chars().take(w.saturating_sub(1).max(1)).collect()
}

fn pad(s: &str, w: usize) -> String {
    let n = s.chars().count();
    if n + 1 >= w { s.to_string() } else { format!("{s}{}", " ".repeat(w - 1 - n)) }
}
