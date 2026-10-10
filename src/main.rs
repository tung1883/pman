//! pman: read man-style docs for any language or tool in the terminal. Docs come as packs
//! (`pman pack install c`); `pman -k words` searches every installed pack.

mod host;
mod index;
mod md;
mod pack;
mod pager;
mod repl;
mod searchidx;
#[cfg(unix)]
mod pty;

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
  pman -k <words> [-t topic|pack]... [-n max] [--all] [--by-page]
                               ranked search of every installed pack
  pman reindex [pack...]       (re)build search.idx for installed packs lacking one
  pman list [topic]            topics, or the pages of one topic
  pman pack list               available and installed packs, grouped
  pman pack install <id|@group>...    download packs or a whole group (or: pack install all)
                               pack remove <id|@group>...   delete them (or: pack remove all)
  pman pack update             update installed packs (and re-import local ones)
  pman pack info <id>          source, upstream version, fetched date, license
  pman pack outdated           installed packs with a newer version or a stale snapshot
  pman license <pack|page>     license of the pack providing a page
  pman add <file.md|dir> [--name n]
                               read your own markdown notes as a pack (pman n); refresh with
                               pman add again or pman pack update, delete with pack remove n

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
        "add" => add(&args[1..]),
        "--repl" => repl(&args[1..]),
        #[cfg(unix)]
        "--pty-host" => {
            let n = |i: usize, d: u16| args.get(i).and_then(|a| a.parse().ok()).unwrap_or(d);
            let code = pty::host(n(1, 80), n(2, 24), &args[3..]);
            std::process::exit(code);
        }
        "list" => {
            let ix = load_index();
            list(&ix, args.get(1).map(String::as_str));
            Ok(())
        }
        "-k" | "--apropos" | "apropos" => {
            ensure_indexes();
            let ix = load_index();
            apropos(&ix, &args[1..])
        }
        "reindex" => reindex(&args[1..]),
        "license" => license(args.get(1).map(String::as_str)),
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
            // Tail match unique to one page (e.g. only w3s.bash_intro) opens directly.
            let tails: Vec<&str> = ix.pages.keys().filter(|id| id.rsplit('.').next() == Some(key.as_str())).map(|s| s.as_str()).collect();
            if tails.len() == 1 {
                let id = tails[0].to_string();
                eprintln!("pman: showing {id}");
                return show(&ix, &id, 0, vec![], false);
            }
            let suggestions = ix.suggest(&key, 8);
            if !suggestions.is_empty() {
                if !(tty() && io::stdin().is_terminal()) {
                    return Err(format!("no manual for '{key}'. Did you mean: {}?", suggestions.join(", ")));
                }
                outln!("no manual for '{key}'. did you mean:");
                for (n, s) in suggestions.iter().enumerate() {
                    outln!("{:>2}. {s}", n + 1);
                }
                print!("open # (enter to quit): ");
                let _ = io::stdout().flush();
                let mut ans = String::new();
                io::stdin().lock().read_line(&mut ans).map_err(|e| e.to_string())?;
                if let Ok(n) = ans.trim().parse::<usize>() {
                    if n >= 1 && n <= suggestions.len() {
                        return show(&ix, &suggestions[n - 1], 0, vec![], false);
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
    let suggestions = ix.suggest_sections(p, q, 5);
    if suggestions.is_empty() {
        eprintln!("pman: no section '{q}' in {}; opening the top", p.id);
    } else {
        eprintln!("pman: no section '{q}' in {}; did you mean: {}? opening the top", p.id, suggestions.join(", "));
    }
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

/// A tutorial's contents page ("w3s.bash_getstarted  Getting started" lines) as a filterable list; Enter opens
/// the page, closing it returns to the list.
fn contents(ix: &Index, toc: &index::Page) -> Result<(), String> {
    // entries are "* w3s.id  Title"; split on the ids so a re-wrapped page parses the same
    let mut items: Vec<(String, String)> = Vec::new();
    let body = toc.lines().iter().take_while(|l| !l.trim_start().starts_with("W3Schools manual"));
    for word in body.flat_map(|l| l.split_whitespace()) {
        if word.starts_with("w3s.") && ix.page(word).is_some() {
            items.push((word.to_string(), String::new()));
        } else if word != "*" {
            if let Some(last) = items.last_mut() {
                if !last.1.is_empty() {
                    last.1.push(' ');
                }
                last.1.push_str(&word.to_lowercase());
            }
        }
    }
    items.retain(|(id, _)| id != &toc.id);
    let title = format!("{} - {} pages", toc.id, items.len());
    let (mut filter, mut selected) = (String::new(), 0usize);
    while let Some(i) = pager::pick(&title, &items, &mut filter, &mut selected).map_err(|e| e.to_string())? {
        show(ix, &items[i].0, 0, vec![], false)?;
    }
    Ok(())
}

/// Shows a page in the pager, or as plain text when stdout is not a terminal.
fn show(ix: &Index, id: &str, line: usize, terms: Vec<String>, section_only: bool) -> Result<(), String> {
    let page = ix.page(id).ok_or("page vanished")?;
    if tty() && io::stdin().is_terminal() && page.id.ends_with("_contents") {
        return contents(ix, page);
    }
    if tty() {
        let mut next = pager::run(page, line, terms).map_err(|e| e.to_string())?;
        while let Some(target) = next {
            let Some(p) = ix.page(&target) else { break };
            if p.id.ends_with("_contents") {
                return contents(ix, p);
            }
            next = pager::run(p, 0, vec![]).map_err(|e| e.to_string())?;
        }
        return Ok(());
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
    let Ok(reg) = pack::fetch_registry_cached() else { return Ok(false) };
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

/// `-t <topic|pack>` expands a pack id to its topics (registry, or the installed pack's own topics).
fn expand_topic_filter(ix: &Index, reg: &Option<pack::Registry>, name: &str) -> Vec<String> {
    let name = name.to_lowercase();
    if let Some(r) = reg {
        if let Some(info) = r.packs.get(&name) {
            if !info.topics.is_empty() {
                return info.topics.clone();
            }
        }
    }
    if ix.topics().contains(&name) {
        return vec![name];
    }
    let mut one = Index::default();
    one.load_pack(&pack::pack_dir(&name));
    let ts = one.topics();
    if !ts.is_empty() {
        return ts;
    }
    vec![name]
}

fn apropos(ix: &Index, args: &[String]) -> Result<(), String> {
    let (mut words, mut topic_names, mut max, mut all, mut by_page) = (Vec::new(), Vec::new(), 15usize, false, false);
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "-t" => topic_names.push(it.next().ok_or("-t needs a value")?.clone()),
            "-n" => max = it.next().ok_or("-n needs a value")?.parse().map_err(|_| "-n needs a number".to_string())?,
            "--all" => all = true,
            "--by-page" => by_page = true,
            _ => words.push(a.clone()),
        }
    }
    let query = words.join(" ");
    if query.trim().is_empty() {
        return Err("usage: pman -k <words> [-t topic|pack]... [-n max] [--all] [--by-page]".into());
    }
    let topics: Option<Vec<String>> = if topic_names.is_empty() {
        None
    } else {
        let reg = pack::fetch_registry_cached().ok();
        Some(topic_names.iter().flat_map(|n| expand_topic_filter(ix, &reg, n)).collect())
    };
    let cap = if all { usize::MAX } else { max.max(1) };
    let mut hits = ix.search_filtered(&query, 0, topics.as_deref());
    hits.sort_by(|a, b| b.score.cmp(&a.score));
    if by_page {
        let mut seen = std::collections::HashSet::new();
        hits.retain(|h| seen.insert(h.page.clone()));
    }
    let mut notes: std::collections::HashMap<(String, usize), String> = std::collections::HashMap::new();
    if !by_page {
        // near-duplicate collapse: same section title in > 3 packs -> keep the best, note the rest
        let mut by_title: std::collections::HashMap<String, Vec<usize>> = std::collections::HashMap::new();
        for (i, h) in hits.iter().enumerate() {
            let p = ix.page(&h.page).unwrap();
            by_title.entry(p.sections()[h.section].title.to_lowercase()).or_default().push(i);
        }
        let mut drop: std::collections::HashSet<usize> = std::collections::HashSet::new();
        for idxs in by_title.values() {
            let packs: std::collections::BTreeSet<&str> = idxs.iter().map(|&i| ix.page(&hits[i].page).unwrap().topic.as_str()).collect();
            if idxs.len() <= 3 || packs.len() <= 3 {
                continue;
            }
            let best = idxs[0];
            for &i in &idxs[1..] {
                drop.insert(i);
            }
            let best_topic = ix.page(&hits[best].page).unwrap().topic.clone();
            let others: Vec<&str> = packs.iter().filter(|t| **t != best_topic).take(3).cloned().collect();
            notes.insert((hits[best].page.clone(), hits[best].section), format!(" (+{} more in {})", idxs.len() - 1, others.join(", ")));
        }
        if !drop.is_empty() {
            hits = hits.into_iter().enumerate().filter(|(i, _)| !drop.contains(i)).map(|(_, h)| h).collect();
        }
    }
    hits.truncate(cap.min(hits.len()));
    if hits.is_empty() {
        outln!("nothing found for '{query}'");
        return Ok(());
    }
    for (n, h) in hits.iter().enumerate() {
        let p = ix.page(&h.page).unwrap();
        let note = notes.get(&(h.page.clone(), h.section)).cloned().unwrap_or_default();
        outln!("{:>2}. {} › {}{}", n + 1, p.id, p.sections()[h.section].title, note);
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

/// Builds `search.idx` for installed packs that do not have one yet (installs from before this
/// feature, or `pman reindex` asked explicitly).
fn reindex(args: &[String]) -> Result<(), String> {
    let ids: Vec<String> = if args.is_empty() { pack::installed().into_iter().map(|(id, _)| id).collect() } else { args.to_vec() };
    let mut n = 0;
    for id in ids {
        let dir = pack::pack_dir(&id);
        if !dir.join("bundle.json").exists() {
            continue;
        }
        index::reindex_installed(&dir).map_err(|e| format!("{id}: {e}"))?;
        outln!("reindexed {id}");
        n += 1;
    }
    if n == 0 {
        outln!("nothing to reindex");
    }
    Ok(())
}

/// `pman license [pack|page]`: the license of the pack providing a page, or of a pack itself.
fn license(key: Option<&str>) -> Result<(), String> {
    let key = key.ok_or("usage: pman license <pack|page>")?;
    let reg = pack::fetch_registry_cached()?;
    let id = if reg.packs.contains_key(key) {
        key.to_string()
    } else {
        let ix = load_index();
        let topic = ix.page(key).map(|p| p.topic.clone()).or_else(|| ix.by_name(key).map(|p| p.topic.clone())).unwrap_or_else(|| key.to_string());
        reg.packs
            .iter()
            .find(|(id, i)| **id == topic || i.topics.iter().any(|t| *t == topic))
            .map(|(id, _)| id.clone())
            .ok_or(format!("no pack found for '{key}'"))?
    };
    let info = reg.packs.get(&id).ok_or(format!("no pack '{id}'"))?;
    match &info.license {
        Some(l) => {
            outln!("{id}: {l}{}", info.license_url.as_deref().map(|u| format!(" ({u})")).unwrap_or_default());
        }
        None => {
            outln!("{id}: license unknown");
        }
    }
    Ok(())
}

/// Quietly (re)builds `search.idx` for any installed pack missing one or whose file a `Reader` can't
/// open (older format version, truncated write): checking the file parses, not just that it exists,
/// so a format bump doesn't leave every `-k` silently falling back to a full scan forever.
fn ensure_indexes() {
    for (id, _) in pack::installed() {
        let dir = pack::pack_dir(&id);
        if !dir.join("bundle.json").exists() {
            continue;
        }
        if searchidx::Reader::open(&dir.join("search.idx")).is_some() {
            continue;
        }
        eprintln!("indexing {id}...");
        if let Err(e) = index::reindex_installed(&dir) {
            eprintln!("pman: failed to index {id}: {e}");
        }
    }
}

// ---- packs -----------------------------------------------------------------------------------

/// `pman --repl [command...]`: a prompt with history and tab completion, for hosts that give pman a
/// terminal but no shell (the phone).
fn repl(initial: &[String]) -> Result<(), String> {
    outln!("pman: topic or page to open, -k words to search, list, pack, exit  (tab completes)");
    let run_line = |words: &[String]| {
        if let Err(e) = run(words) {
            if !e.is_empty() {
                eprintln!("pman: {e}");
            }
        }
    };
    if !initial.is_empty() {
        run_line(initial);
    }
    let interactive = io::stdin().is_terminal();
    let mut history = repl::History::load();
    let mut words = completion_words();
    loop {
        let line = if interactive {
            match repl::read_line("pman> ", &history, &|b| complete(&words, b)).map_err(|e| e.to_string())? {
                Some(l) => l,
                None => return Ok(()),
            }
        } else {
            print!("pman> ");
            let _ = io::stdout().flush();
            let mut l = String::new();
            if io::stdin().lock().read_line(&mut l).map_err(|e| e.to_string())? == 0 {
                return Ok(());
            }
            l
        };
        history.add(line.trim());
        let mut args: Vec<String> = line.split_whitespace().map(String::from).collect();
        if args.first().map_or(false, |w| w == "pman" || w == "man") {
            args.remove(0);
        }
        match args.first().map(String::as_str) {
            None => continue,
            Some("exit") | Some("quit") => return Ok(()),
            Some("clear") => {
                print!("\x1b[2J\x1b[H");
                continue;
            }
            _ => {}
        }
        let changes_packs = matches!(args[0].as_str(), "pack" | "add");
        run_line(&args);
        if changes_packs {
            words = completion_words();
        }
    }
}

struct Words {
    first: Vec<String>,
    subs: std::collections::HashMap<String, Vec<String>>,
    topics: Vec<String>,
    packs: Vec<String>,
}

fn completion_words() -> Words {
    let ix = load_index();
    let mut first: std::collections::BTreeSet<String> =
        ["list", "pack", "add", "exit", "clear", "help", "reindex", "license"].iter().map(|s| s.to_string()).collect();
    let mut subs: std::collections::HashMap<String, Vec<String>> = std::collections::HashMap::new();
    for p in ix.pages.values() {
        first.insert(p.topic.clone());
        if p.id.len() > p.topic.len() {
            subs.entry(p.topic.clone()).or_default().push(p.id[p.topic.len() + 1..].to_string());
        }
        for a in &p.aliases {
            first.insert(a.clone());
        }
    }
    let mut packs: std::collections::BTreeSet<String> = pack::installed().into_iter().map(|(id, _)| id).collect();
    if let Ok(reg) = pack::fetch_registry_cached() {
        packs.extend(reg.packs.keys().cloned());
    }
    let topics = ix.topics();
    Words { first: first.into_iter().collect(), subs, topics, packs: packs.into_iter().collect() }
}

/// What can follow `before` (the line up to the cursor): (char index where the current word starts, matches).
fn complete(w: &Words, before: &str) -> (usize, Vec<String>) {
    let cur: String = if before.ends_with(char::is_whitespace) { String::new() } else { before.split_whitespace().last().unwrap_or("").to_string() };
    let start = before.chars().count() - cur.chars().count();
    let mut prev: Vec<&str> = before[..before.len() - cur.len()].split_whitespace().collect();
    if prev.first().map_or(false, |p| *p == "pman" || *p == "man") {
        prev.remove(0);
    }
    let lc = cur.to_lowercase();
    let pool: Vec<String> = match prev.as_slice() {
        [] => w.first.clone(),
        ["pack"] => ["install", "list", "remove", "update", "info", "outdated"].iter().map(|s| s.to_string()).collect(),
        ["pack", "install"] | ["pack", "remove"] => w.packs.clone(),
        ["pack", "info"] => w.packs.clone(),
        ["license"] => w.packs.clone(),
        ["list"] => w.topics.clone(),
        [topic] => w.subs.get(&topic.to_lowercase()).cloned().unwrap_or_default(),
        _ => Vec::new(),
    };
    let mut found: Vec<String> = pool.into_iter().filter(|c| c.to_lowercase().starts_with(&lc)).collect();
    found.sort();
    found.dedup();
    (start, found)
}

fn add(args: &[String]) -> Result<(), String> {
    let (mut path, mut name) = (None, None);
    let mut it = args.iter();
    while let Some(a) = it.next() {
        if a == "--name" || a == "-n" {
            name = Some(it.next().ok_or("--name needs a value")?.clone());
        } else if path.is_none() {
            path = Some(a.clone());
        } else {
            return Err("usage: pman add <file.md|dir|pack.zip> [--name n]".into());
        }
    }
    let path = path.ok_or("usage: pman add <file.md|dir|pack.zip> [--name n]")?;
    let src = std::path::Path::new(&path);
    if !src.exists() {
        return Err(format!("{path}: no such file or folder"));
    }
    let name = name
        .or_else(|| {
            let abs = std::fs::canonicalize(src).ok()?;
            abs.file_stem().map(|s| s.to_string_lossy().to_string())
        })
        .map(|n| md::slug(std::path::Path::new(&n)))
        .filter(|n| !n.is_empty())
        .ok_or("cannot derive a name; use --name")?;
    import_local(&name, src)
}

fn import_local(name: &str, src: &std::path::Path) -> Result<(), String> {
    const RESERVED: [&str; 10] = ["pack", "list", "add", "help", "update", "remove", "install", "all", "reindex", "license"];
    if RESERVED.contains(&name) {
        return Err(format!("'{name}' is a pman command; pick another with --name"));
    }
    if pack::installed_version(name).is_some() && pack::local_source(name).is_none() {
        return Err(format!("'{name}' is an installed doc pack; pick another with --name"));
    }
    let known = pack::fetch_registry_cached().map(|r| r.packs.contains_key(name)).unwrap_or(false);
    if known && pack::local_source(name).is_none() {
        return Err(format!("'{name}' is a downloadable doc pack; pick another with --name"));
    }
    let again = pack::local_source(name).is_some();
    let n = pack::add_local(name, src)?;
    outln!("{} {name}: {n} page{} (pman {name})", if again { "updated" } else { "added" }, if n == 1 { "" } else { "s" });
    Ok(())
}

/// Days since the Unix epoch for a "YYYY-MM-DD" string (Howard Hinnant's `days_from_civil`).
fn parse_date(s: &str) -> Option<i64> {
    let mut it = s.split('-');
    let y: i64 = it.next()?.parse().ok()?;
    let m: i64 = it.next()?.parse().ok()?;
    let d: i64 = it.next()?.parse().ok()?;
    let y = if m <= 2 { y - 1 } else { y };
    let era = if y >= 0 { y } else { y - 399 } / 400;
    let yoe = y - era * 400;
    let mp = (m + 9) % 12;
    let doy = (153 * mp + 2) / 5 + d - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    Some(era * 146097 + doe - 719468)
}

fn days_since(epoch_days: i64) -> i64 {
    let now = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64 / 86400).unwrap_or(0);
    now - epoch_days
}

/// `@devops` is always a group; a bare `devops` is a group only when no pack has that id.
fn expand_group_ids(reg: &pack::Registry, ids: &[String]) -> Vec<String> {
    let mut out = Vec::new();
    for id in ids {
        let bare = id.strip_prefix('@').unwrap_or(id);
        if (id.starts_with('@') || !reg.packs.contains_key(id.as_str())) && reg.groups.contains_key(bare) {
            for p in &reg.groups[bare].packs {
                if !out.contains(p) {
                    out.push(p.clone());
                }
            }
        } else {
            out.push(id.clone());
        }
    }
    out
}

fn packs(args: &[String]) -> Result<(), String> {
    let sub = args.first().map(String::as_str).unwrap_or("list");
    match sub {
        "list" => {
            let installed = pack::installed();
            for (id, _) in &installed {
                if let Some(src) = pack::local_source(id) {
                    outln!("  {id:<8} {:<18} {}", "local", src.display());
                }
            }
            match pack::fetch_registry_cached() {
                Ok(reg) => {
                    let state = |id: &str, info: &pack::PackInfo| match pack::installed_version(id) {
                        Some(v) if v == info.version => "[installed]".to_string(),
                        Some(_) => "[update available]".to_string(),
                        None => format!("{:.1} MB", info.size as f64 / 1048576.0),
                    };
                    let mut grouped: std::collections::HashSet<&str> = std::collections::HashSet::new();
                    for (gname, g) in &reg.groups {
                        let members: Vec<(&String, &pack::PackInfo)> =
                            g.packs.iter().filter_map(|id| reg.packs.get(id).map(|i| (id, i))).collect();
                        if members.is_empty() {
                            continue;
                        }
                        let total_mb: f64 = members.iter().map(|(_, i)| i.size as f64 / 1048576.0).sum();
                        outln!("@{gname} - {} ({total_mb:.1} MB total)", g.desc);
                        for (id, info) in &members {
                            if pack::local_source(id).is_some() {
                                continue;
                            }
                            grouped.insert(id.as_str());
                            outln!("  {id:<8} {:<20} {}", state(id, info), info.desc);
                        }
                    }
                    for (id, info) in &reg.packs {
                        if pack::local_source(id).is_some() || grouped.contains(id.as_str()) {
                            continue;
                        }
                        outln!("  {id:<8} {:<20} {}", state(id, info), info.desc);
                    }
                }
                Err(e) => {
                    eprintln!("pman: {e}");
                    for (id, v) in installed {
                        if pack::local_source(&id).is_some() {
                            continue;
                        }
                        outln!("  {id:<8} installed (v{v})");
                    }
                }
            }
            Ok(())
        }
        "info" => {
            let id = args.get(1).ok_or("usage: pman pack info <id>")?;
            let reg = pack::fetch_registry_cached()?;
            let info = reg.packs.get(id).ok_or(format!("no pack '{id}' (pman pack list)"))?;
            outln!("{id}: {}", info.desc);
            outln!("  registry version: {}", info.version);
            if let Some(v) = pack::installed_version(id) {
                outln!("  installed version: {v}{}", if v == info.version { " (up to date)" } else { " (update available)" });
            } else {
                outln!("  not installed ({:.1} MB)", info.size as f64 / 1048576.0);
            }
            if let Some(g) = &info.group {
                outln!("  group: @{g}");
            }
            if let Some(s) = &info.source {
                outln!("  source: {s}");
            }
            if let Some(v) = &info.upstream_version {
                outln!("  upstream version: {v}");
            }
            if let Some(f) = &info.fetched {
                outln!("  fetched: {f}");
            }
            if let Some(l) = &info.license {
                outln!("  license: {l}{}", info.license_url.as_deref().map(|u| format!(" ({u})")).unwrap_or_default());
            }
            Ok(())
        }
        "outdated" => {
            let reg = pack::fetch_registry()?;
            let mut any = false;
            for (id, v) in pack::installed() {
                if pack::local_source(&id).is_some() {
                    continue;
                }
                let Some(info) = reg.packs.get(&id) else { continue };
                let stale = info
                    .fetched
                    .as_deref()
                    .and_then(|d| parse_date(d))
                    .map_or(false, |days| days_since(days) > 365);
                if v < info.version || stale {
                    any = true;
                    let tag = if v < info.version && stale {
                        "update available, stale"
                    } else if v < info.version {
                        "update available"
                    } else {
                        "stale?"
                    };
                    outln!("  {id:<8} v{v} -> v{} ({tag})", info.version);
                }
            }
            if !any {
                outln!("all packs up to date");
            }
            Ok(())
        }
        "install" | "update" | "remove" => {
            // `update` means "check for real"; everything else is happy with a <24h cached copy, so
            // one fetch serves both the group lookup below and the install/update pass further down.
            let group_reg = if sub == "update" { pack::fetch_registry().ok() } else { pack::fetch_registry_cached().ok() };
            let ids: Vec<String> = args[1..].to_vec();
            if sub == "remove" {
                if ids.is_empty() {
                    return Err("usage: pman pack remove <id>... | @group | all".into());
                }
                let ids = if ids.iter().any(|i| i == "all" || i == "--all") {
                    pack::installed().into_iter().map(|(id, _)| id).collect()
                } else if let Some(reg) = &group_reg {
                    expand_group_ids(reg, &ids)
                } else {
                    ids
                };
                for id in ids {
                    pack::remove(&id).map_err(|e| e.to_string())?;
                    outln!("removed {id}");
                }
                return Ok(());
            }
            let mut locals = 0;
            if sub == "update" {
                for (id, _) in pack::installed() {
                    if let Some(src) = pack::local_source(&id) {
                        if !src.exists() {
                            eprintln!("pman: source of '{id}' is gone ({}); keeping the imported copy", src.display());
                        } else if pack::local_source_stale(&id, &src) {
                            import_local(&id, &src)?;
                        }
                        locals += 1;
                    }
                }
            }
            let reg = match group_reg {
                Some(r) => r,
                None => pack::fetch_registry()?,
            };
            let targets: Vec<String> = if sub == "update" {
                pack::installed().into_iter().map(|(id, _)| id).filter(|id| pack::local_source(id).is_none()).collect()
            } else if ids.iter().any(|i| i == "all" || i == "--all") {
                reg.packs.keys().cloned().collect()
            } else {
                let expanded = expand_group_ids(&reg, &ids);
                if expanded.len() > ids.len() {
                    let new_mb: f64 = expanded
                        .iter()
                        .filter(|id| reg.packs.contains_key(*id) && pack::installed_version(id) != reg.packs.get(*id).map(|i| i.version))
                        .filter_map(|id| reg.packs.get(id))
                        .map(|i| i.size as f64 / 1048576.0)
                        .sum();
                    if io::stdin().is_terminal() && io::stderr().is_terminal() {
                        eprint!("group expands to {} packs, {new_mb:.1} MB to download. proceed? [Y/n] ", expanded.len());
                        let _ = io::stderr().flush();
                        let mut ans = String::new();
                        io::stdin().lock().read_line(&mut ans).map_err(|e| e.to_string())?;
                        if !matches!(ans.trim().to_lowercase().as_str(), "" | "y" | "yes") {
                            return Ok(());
                        }
                    } else {
                        eprintln!("pman: group expands to {} packs, {new_mb:.1} MB", expanded.len());
                    }
                }
                expanded
            };
            if targets.is_empty() {
                if sub == "update" && locals > 0 {
                    return Ok(());
                }
                return Err(if sub == "update" { "nothing installed".into() } else { "usage: pman pack install <id>...".into() });
            }
            let mut current = 0;
            let mut to_install: Vec<(String, u32, Option<u32>)> = Vec::new();
            for id in targets {
                let Some(info) = reg.packs.get(&id) else {
                    if sub == "update" {
                        eprintln!("pman: '{id}' is no longer in the registry; keeping the installed copy");
                        continue;
                    }
                    return Err(format!("no pack '{id}' (pman pack list)"));
                };
                if pack::local_source(&id).is_some() {
                    return Err(format!("'{id}' is one of your local packs; remove it first (pman pack remove {id})"));
                }
                let old = pack::installed_version(&id);
                if old == Some(info.version) {
                    outln!("{id} is up to date (v{})", info.version);
                    current += 1;
                    continue;
                }
                to_install.push((id, info.version, old));
            }
            let changed = install_parallel(&reg, to_install)?;
            if sub == "update" {
                outln!("{changed} updated, {current} already up to date");
            }
            Ok(())
        }
        _ => Err("usage: pman pack list | install <id|@group>... | remove <id|@group>... | update | info <id> | outdated".into()),
    }
}

/// Installs/updates several packs concurrently (network download dominates, so this overlaps their
/// latency instead of paying it one pack at a time, as `pack install all` does). A lone pack keeps
/// the live progress bar; two or more install quietly and report as each finishes, since interleaved
/// progress bars would garble the terminal.
fn install_parallel(reg: &pack::Registry, to_install: Vec<(String, u32, Option<u32>)>) -> Result<usize, String> {
    if to_install.is_empty() {
        return Ok(0);
    }
    if to_install.len() == 1 {
        let (id, version, old) = &to_install[0];
        let info = reg.packs.get(id).expect("checked above");
        pack::install(id, info, false)?;
        match old {
            Some(v) => { outln!("updated {id} v{v} -> v{version}"); }
            None => { outln!("installed {id} v{version}"); }
        }
        return Ok(1);
    }
    let workers = std::thread::available_parallelism().map(|n| n.get()).unwrap_or(4).min(8).min(to_install.len());
    let queue = std::sync::Mutex::new(to_install.into_iter());
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::scope(|scope| {
        for _ in 0..workers {
            let queue = &queue;
            let tx = tx.clone();
            scope.spawn(move || loop {
                let next = queue.lock().unwrap().next();
                let Some((id, version, old)) = next else { break };
                let info = reg.packs.get(&id).expect("checked above");
                let result = pack::install(&id, info, true);
                let _ = tx.send((id, version, old, result));
            });
        }
    });
    drop(tx);
    let (mut changed, mut failed) = (0, 0);
    for (id, version, old, result) in rx {
        match result {
            Ok(()) => {
                match old {
                    Some(v) => { outln!("updated {id} v{v} -> v{version}"); }
                    None => { outln!("installed {id} v{version}"); }
                }
                changed += 1;
            }
            Err(e) => {
                eprintln!("pman: {id}: {e}");
                failed += 1;
            }
        }
    }
    if changed == 0 && failed > 0 {
        return Err(format!("{failed} pack(s) failed to install"));
    }
    if failed > 0 {
        eprintln!("pman: {failed} pack(s) failed to install, {changed} installed");
    }
    Ok(changed)
}

