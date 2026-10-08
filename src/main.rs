//! pman: read man-style docs for any language or tool in the terminal. Docs come as packs
//! (`pman pack install c`); `pman -k words` searches every installed pack.

mod index;
mod pack;
mod pager;

use index::Index;
use std::io::{self, BufRead, IsTerminal, Write};
use std::process::ExitCode;

macro_rules! outln {
    ($($a:tt)*) => {
        // a closed pipe (| head) is not an error worth a panic
        let _ = writeln!(io::stdout(), $($a)*);
    };
}

const USAGE: &str = "\
pman: man-style docs for languages and tools

usage:
  pman <topic> [section...]    open a page or jump to a section
  pman <function>              open the page that documents it (pman sprintf)
  pman -k <words>              ranked search of every installed pack
  pman list [topic]            topics, or the pages of one topic
  pman pack list               available and installed packs
  pman pack install <id>...    download packs (or: pack install all)
                               pack remove <id>...   delete them (or: pack remove all)
  pman pack update             update installed packs

examples:
  pman c printf        pman c syntax        pman ts generics
  pman py str.join     pman -k type guard   pman c 2.1

in a page: j/k line  space/b page  d/u half  g/G ends  / search  n/N next/prev  t sections  q quit
When output is not a terminal the page is printed as plain text.
env: PMAN_HOME (data dir), PMAN_REGISTRY (registry URL or file), PMAN_DOCS (extra docs dir)";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    match run(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(msg) => {
            if !msg.is_empty() {
                eprintln!("pman: {msg}");
            }
            ExitCode::from(1)
        }
    }
}

fn run(args: &[String]) -> Result<(), String> {
    let Some(first) = args.first() else {
        outln!("{USAGE}");
        return Ok(());
    };
    match first.as_str() {
        "-h" | "--help" | "help" => {
            outln!("{USAGE}");
            Ok(())
        }
        "-V" | "--version" => {
            outln!("pman {}", env!("CARGO_PKG_VERSION"));
            Ok(())
        }
        "pack" => packs(&args[1..]),
        "list" => {
            let ix = load_index();
            list(&ix, args.get(1).map(String::as_str));
            Ok(())
        }
        "-k" | "--apropos" | "apropos" => {
            let ix = load_index();
            apropos(&ix, &args[1..].join(" "))
        }
        _ => lookup(args),
    }
}

fn load_index() -> Index {
    let mut ix = Index::default();
    for (id, _) in pack::installed() {
        ix.load_pack(&pack::pack_dir(&id));
    }
    if let Ok(dir) = std::env::var("PMAN_DOCS") {
        if let Ok(rd) = std::fs::read_dir(&dir) {
            for e in rd.flatten() {
                ix.scan(&e.path().join("man"));
            }
        }
    }
    ix
}

fn tty() -> bool {
    io::stdout().is_terminal()
}

// ---- lookup ----------------------------------------------------------------------------------

fn lookup(args: &[String]) -> Result<(), String> {
    let mut ix = load_index();
    match resolve(&ix, args) {
        Resolved::Page(id, line, section_only) => show(&ix, &id, line, vec![], section_only),
        Resolved::Topic(t) => browse(&ix, &t),
        Resolved::Choose(found) => choose(&ix, &found, &args[1..].join(" ")),
        Resolved::Missing(msg) => {
            // `pman web`: the name of an installed pack lists the topics inside it.
            let key = args[0].to_lowercase();
            if args.len() == 1 && pack::installed_version(&key).is_some() {
                let mut one = Index::default();
                one.load_pack(&pack::pack_dir(&key));
                outln!("pack '{key}' holds these topics (pman <topic> [page]):");
                for t in one.topics() {
                    let n = one.sub_pages(&t).len();
                    if n > 0 {
                        outln!("  {t:<10} {n} pages   (pman list {t})");
                    } else {
                        outln!("  {t}");
                    }
                }
                return Ok(());
            }
            // Not found locally: maybe a pack that is not installed has it.
            if try_install_for(&args[0])? {
                ix = load_index();
                if let Resolved::Page(id, line, so) = resolve(&ix, args) {
                    return show(&ix, &id, line, vec![], so);
                }
                if let Resolved::Topic(t) = resolve(&ix, args) {
                    return browse(&ix, &t);
                }
                if let Resolved::Choose(found) = resolve(&ix, args) {
                    return choose(&ix, &found, &args[1..].join(" "));
                }
            }
            Err(msg)
        }
    }
}

enum Resolved {
    /// page id, start line, whether only that section should be printed in plain-text mode
    Page(String, usize, bool),
    Topic(String),
    /// several sections match; (page, section, score)
    Choose(Vec<(String, usize, i32)>),
    Missing(String),
}

fn resolve(ix: &Index, args: &[String]) -> Resolved {
    let key = args[0].to_lowercase();
    let rest = args[1..].join(" ");
    let mut page = ix.page(&key);
    let mut rest = rest;
    if page.is_none() && key.contains('.') {
        // pman py.str.join -> page py.str, section join
        let mut k = key.clone();
        while page.is_none() && k.contains('.') {
            k.truncate(k.rfind('.').unwrap());
            page = ix.page(&k);
        }
        if page.is_some() {
            rest = format!("{} {}", &key[k.len() + 1..], rest).trim().to_string();
        }
    }
    if page.is_none() && args.len() > 1 && ix.sub_pages(&key).is_empty() {
        // pman docker run -> the page that documents "docker-run"
        if let Some(p) = ix.by_name(&format!("{key}-{}", args[1].to_lowercase())) {
            return open_query(ix, p, &args[2..].join(" "));
        }
    }
    if page.is_none() && ix.sub_pages(&key).is_empty() {
        page = ix.by_name(&key); // pman sprintf
    }
    if let Some(p) = page {
        if p.id == key && args.len() > 1 && !ix.sub_pages(&key).is_empty() {
            // pman js array map -> js.array-map ; pman bash ref -> bash.ref
            let joined = format!("{key}.{}", args[1..].join("-").to_lowercase());
            if let Some(sp) = ix.page(&joined) {
                return open_query(ix, sp, "");
            }
            if let Some(sp) = ix.page(&format!("{key}.{}", args[1].to_lowercase())) {
                return open_query(ix, sp, &args[2..].join(" "));
            }
        }
        return open_query(ix, p, &rest);
    }
    if !ix.sub_pages(&key).is_empty() {
        if rest.is_empty() {
            return Resolved::Topic(key);
        }
        // pman cpp vector push_back -> cpp.vector-push_back ; pman css selector hover -> css.selector-hover
        let joined = format!("{key}.{}", args[1..].join("-").to_lowercase());
        if let Some(sp) = ix.page(&joined) {
            return open_query(ix, sp, "");
        }
        let first = args[1].to_lowercase();
        let mut sub = ix.page(&format!("{key}.{first}"));
        if sub.is_none() {
            if let Some(a) = ix.by_name(&first) {
                if a.topic == key {
                    sub = Some(a);
                }
            }
        }
        if let Some(sp) = sub {
            return open_query(ix, sp, &args[2..].join(" "));
        }
        return topic_sections(ix, &key, &rest)
            .unwrap_or_else(|| Resolved::Missing(format!("no section '{rest}' in {key} (try: pman -k {rest})")));
    }
    Resolved::Missing(format!("no manual for '{key}' (pman list shows what is installed)"))
}

fn open_query(ix: &Index, p: &index::Page, q: &str) -> Resolved {
    if q.is_empty() {
        return Resolved::Page(p.id.clone(), 0, false);
    }
    if let Some(s) = ix.find_section(p, q) {
        return Resolved::Page(p.id.clone(), p.sections()[s].line, true);
    }
    // Not a section of this page: maybe one of its topic's other pages (pman bash cd -> bash.ref).
    if let Some(r) = topic_sections(ix, &p.topic, q) {
        return r;
    }
    eprintln!("pman: no section '{q}' in {}; opening the top", p.id);
    Resolved::Page(p.id.clone(), 0, false)
}

/// Sections of a topic matching `q`: one is opened, several are offered as a list in a terminal.
fn topic_sections(ix: &Index, topic: &str, q: &str) -> Option<Resolved> {
    let found = ix.find_in_topic(topic, q);
    let best = found.first()?;
    if best.2 < 4 && found.len() > 1 && tty() && io::stdin().is_terminal() {
        return Some(Resolved::Choose(found.into_iter().take(12).collect()));
    }
    let line = ix.page(&best.0)?.sections()[best.1].line;
    Some(Resolved::Page(best.0.clone(), line, true))
}

/// `pman html`: in a terminal an interactive, filterable list of the topic's pages (Enter opens a page,
/// closing it returns to the list); otherwise a plain listing.
fn browse(ix: &Index, topic: &str) -> Result<(), String> {
    if !(tty() && io::stdin().is_terminal()) {
        list(ix, Some(topic));
        return Ok(());
    }
    let pages = ix.sub_pages(topic);
    let items: Vec<(String, String)> = pages.iter().map(|p| (p.id.clone(), p.title.to_lowercase())).collect();
    let title = format!("{topic} - {} pages", items.len());
    let (mut filter, mut selected) = (String::new(), 0usize);
    while let Some(i) = pager::pick(&title, &items, &mut filter, &mut selected).map_err(|e| e.to_string())? {
        show(ix, &items[i].0, 0, vec![], false)?;
    }
    Ok(())
}

/// Several sections match a section query: list them and let the user pick one.
fn choose(ix: &Index, found: &[(String, usize, i32)], query: &str) -> Result<(), String> {
    for (n, (id, s, _)) in found.iter().enumerate() {
        let p = ix.page(id).unwrap();
        outln!("{:>2}. {} › {}", n + 1, p.id, p.sections()[*s].title);
    }
    print!("open # (enter to quit): ");
    let _ = io::stdout().flush();
    let mut ans = String::new();
    io::stdin().lock().read_line(&mut ans).map_err(|e| e.to_string())?;
    if let Ok(n) = ans.trim().parse::<usize>() {
        if n >= 1 && n <= found.len() {
            let (id, s, _) = &found[n - 1];
            let line = ix.page(id).unwrap().sections()[*s].line;
            let terms = query.to_lowercase().split_whitespace().map(String::from).collect();
            return show(ix, id, line, terms, true);
        }
    }
    Ok(())
}

/// Shows a page in the pager, or as plain text when stdout is not a terminal.
fn show(ix: &Index, id: &str, line: usize, terms: Vec<String>, section_only: bool) -> Result<(), String> {
    let page = ix.page(id).ok_or("page vanished")?;
    if tty() {
        return pager::run(page, line, terms).map_err(|e| e.to_string());
    }
    let (from, to) = if section_only {
        let s = page.section_at(line);
        let end = page.sections().get(s + 1).map_or(page.lines().len(), |n| n.line);
        (page.sections()[s].line, end)
    } else {
        (0, page.lines().len())
    };
    let mut out = io::stdout().lock();
    for l in &page.lines()[from..to] {
        if writeln!(out, "{l}").is_err() {
            break; // closed pipe, e.g. | head
        }
    }
    Ok(())
}

/// If a registry pack provides `key` and it is not installed, offers to install it. Returns true when installed.
fn try_install_for(key: &str) -> Result<bool, String> {
    let topic = key.split('.').next().unwrap_or(key).to_lowercase();
    let Ok(reg) = pack::fetch_registry() else { return Ok(false) };
    let Some((id, info)) = reg
        .packs
        .iter()
        .find(|(id, i)| **id == topic || i.topics.iter().any(|t| *t == topic))
    else {
        return Ok(false);
    };
    if pack::installed_version(id) == Some(info.version) {
        return Ok(false);
    }
    eprintln!("pman: '{topic}' docs are in the '{id}' pack, not installed ({:.1} MB).", info.size as f64 / 1048576.0);
    if !(io::stdin().is_terminal() && io::stderr().is_terminal()) {
        return Err(format!("run: pman pack install {id}"));
    }
    eprint!("install now? [Y/n] ");
    let _ = io::stderr().flush();
    let mut ans = String::new();
    io::stdin().lock().read_line(&mut ans).map_err(|e| e.to_string())?;
    if matches!(ans.trim().to_lowercase().as_str(), "" | "y" | "yes") {
        pack::install(id, info, false)?;
        eprintln!("installed {id}");
        Ok(true)
    } else {
        Ok(false)
    }
}

// ---- list / search ---------------------------------------------------------------------------

fn list(ix: &Index, topic: Option<&str>) {
    if ix.pages.is_empty() {
        outln!("no docs installed. try: pman pack list");
        return;
    }
    match topic {
        None => {
            for t in ix.topics() {
                let n = ix.sub_pages(&t).len();
                if n > 0 {
                    outln!("  {t:<10} {n} pages");
                } else {
                    outln!("  {t}");
                }
            }
        }
        Some(t) => {
            for p in ix.sub_pages(t) {
                outln!("  {:<18} {}", p.id, p.title.to_lowercase());
            }
        }
    }
}

fn apropos(ix: &Index, query: &str) -> Result<(), String> {
    if query.trim().is_empty() {
        return Err("usage: pman -k <words>".into());
    }
    let hits = ix.search(query, 30);
    if hits.is_empty() {
        outln!("nothing found for '{query}'");
        return Ok(());
    }
    for (n, h) in hits.iter().enumerate() {
        let p = ix.page(&h.page).unwrap();
        outln!("{:>2}. {} › {}", n + 1, p.id, p.sections()[h.section].title);
        if !h.snippet.is_empty() {
            outln!("      {}", h.snippet);
        }
    }
    if !(tty() && io::stdin().is_terminal()) {
        return Ok(());
    }
    print!("open # (enter to quit): ");
    let _ = io::stdout().flush();
    let mut ans = String::new();
    io::stdin().lock().read_line(&mut ans).map_err(|e| e.to_string())?;
    if let Ok(n) = ans.trim().parse::<usize>() {
        if n >= 1 && n <= hits.len() {
            let h = &hits[n - 1];
            let terms = query.to_lowercase().split_whitespace().map(String::from).collect();
            return show(ix, &h.page, h.line, terms, false);
        }
    }
    Ok(())
}

// ---- packs -----------------------------------------------------------------------------------

fn packs(args: &[String]) -> Result<(), String> {
    let sub = args.first().map(String::as_str).unwrap_or("list");
    match sub {
        "list" => {
            let installed = pack::installed();
            match pack::fetch_registry() {
                Ok(reg) => {
                    for (id, info) in &reg.packs {
                        let state = match pack::installed_version(id) {
                            Some(v) if v == info.version => "installed".to_string(),
                            Some(_) => "update available".to_string(),
                            None => format!("{:.1} MB", info.size as f64 / 1048576.0),
                        };
                        outln!("  {id:<8} {state:<18} {}", info.desc);
                    }
                }
                Err(e) => {
                    eprintln!("pman: {e}");
                    for (id, v) in installed {
                        outln!("  {id:<8} installed (v{v})");
                    }
                }
            }
            Ok(())
        }
        "install" | "update" | "remove" => {
            let ids: Vec<String> = args[1..].to_vec();
            if sub == "remove" {
                if ids.is_empty() {
                    return Err("usage: pman pack remove <id>... | all".into());
                }
                let ids = if ids.iter().any(|i| i == "all" || i == "--all") {
                    pack::installed().into_iter().map(|(id, _)| id).collect()
                } else {
                    ids
                };
                for id in ids {
                    pack::remove(&id).map_err(|e| e.to_string())?;
                    outln!("removed {id}");
                }
                return Ok(());
            }
            let reg = pack::fetch_registry()?;
            let targets: Vec<String> = if sub == "update" {
                pack::installed().into_iter().map(|(id, _)| id).collect()
            } else if ids.iter().any(|i| i == "all" || i == "--all") {
                reg.packs.keys().cloned().collect()
            } else {
                ids
            };
            if targets.is_empty() {
                return Err(if sub == "update" { "nothing installed".into() } else { "usage: pman pack install <id>...".into() });
            }
            let (mut changed, mut current) = (0, 0);
            for id in targets {
                let Some(info) = reg.packs.get(&id) else {
                    if sub == "update" {
                        eprintln!("pman: '{id}' is no longer in the registry; keeping the installed copy");
                        continue;
                    }
                    return Err(format!("no pack '{id}' (pman pack list)"));
                };
                let old = pack::installed_version(&id);
                if old == Some(info.version) {
                    outln!("{id} is up to date (v{})", info.version);
                    current += 1;
                    continue;
                }
                pack::install(&id, info, false)?;
                if let Some(v) = old {
                    outln!("updated {id} v{v} -> v{}", info.version);
                } else {
                    outln!("installed {id} v{}", info.version);
                }
                changed += 1;
            }
            if sub == "update" {
                outln!("{changed} updated, {current} already up to date");
            }
            Ok(())
        }
        _ => Err("usage: pman pack list | install <id>... | remove <id>... | update".into()),
    }
}

