//! Doc packs: zips of man-style text downloaded on demand into the data dir.
//!
//! A pack lives in `<data>/packs/<id>/` and counts as installed only when its `.version` marker
//! matches the registry. Install = download to `<id>.zip.part` (resumable), verify sha256, unzip
//! into `<id>.tmp`, rename; a failure at any step leaves the pack "not installed".

use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs::{self, File};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime};

/// Default registry; override with `PMAN_REGISTRY` (a URL or a local file path).
pub const DEFAULT_REGISTRY: &str = "https://github.com/tung1883/pman/releases/latest/download/registry.json";
const STALE_PART: Duration = Duration::from_secs(7 * 24 * 60 * 60);

#[derive(Deserialize, Clone)]
pub struct PackInfo {
    pub version: u32,
    pub url: String,
    pub sha256: String,
    pub size: u64,
    #[serde(default)]
    pub topics: Vec<String>,
    #[serde(default)]
    pub desc: String,
}

#[derive(Deserialize)]
pub struct Registry {
    pub packs: BTreeMap<String, PackInfo>,
}

pub fn data_dir() -> PathBuf {
    if let Ok(p) = std::env::var("PMAN_HOME") {
        return PathBuf::from(p);
    }
    dirs::data_dir().unwrap_or_else(|| PathBuf::from(".")).join("pman")
}

pub fn packs_dir() -> PathBuf {
    data_dir().join("packs")
}

pub fn pack_dir(id: &str) -> PathBuf {
    packs_dir().join(id)
}

pub fn installed_version(id: &str) -> Option<u32> {
    fs::read_to_string(pack_dir(id).join(".version")).ok()?.trim().parse().ok()
}

/// Installed packs, `(id, version)`.
pub fn installed() -> Vec<(String, u32)> {
    let mut out = Vec::new();
    if let Ok(rd) = fs::read_dir(packs_dir()) {
        for e in rd.flatten() {
            let id = e.file_name().to_string_lossy().to_string();
            if let Some(v) = installed_version(&id) {
                out.push((id, v));
            }
        }
    }
    out.sort();
    out
}

/// A local pack (made by `pman add`) records where it came from in `.source`.
pub fn local_source(id: &str) -> Option<PathBuf> {
    let s = fs::read_to_string(pack_dir(id).join(".source")).ok()?;
    Some(PathBuf::from(s.trim()))
}

/// Imports a .md file or folder of them as the local pack `name`, replacing an earlier import.
pub fn add_local(name: &str, src: &Path) -> Result<usize, String> {
    let notes = crate::md::convert_source(src, name);
    if notes.is_empty() {
        return Err(format!("no .md files in {}", src.display()));
    }
    let root = packs_dir();
    let tmp = root.join(format!("{name}.tmp"));
    let _ = fs::remove_dir_all(&tmp);
    let man = tmp.join("man");
    fs::create_dir_all(&man).map_err(|e| e.to_string())?;
    for n in &notes {
        let path = if n.slug.is_empty() { man.join(format!("{name}.txt")) } else { man.join(name).join(format!("{}.txt", n.slug)) };
        if let Some(d) = path.parent() {
            fs::create_dir_all(d).map_err(|e| e.to_string())?;
        }
        fs::write(&path, &n.text).map_err(|e| e.to_string())?;
    }
    crate::index::build_bundle(&tmp).map_err(|e| e.to_string())?;
    let abs = fs::canonicalize(src).unwrap_or_else(|_| src.to_path_buf());
    let abs = abs.to_string_lossy().to_string();
    let abs = abs.strip_prefix("\\\\?\\").unwrap_or(&abs).to_string();
    fs::write(tmp.join(".source"), abs).map_err(|e| e.to_string())?;
    fs::write(tmp.join(".version"), "0").map_err(|e| e.to_string())?;
    let dest = pack_dir(name);
    let _ = fs::remove_dir_all(&dest);
    fs::rename(&tmp, &dest).map_err(|e| e.to_string())?;
    Ok(notes.len())
}

pub fn remove(id: &str) -> io::Result<()> {
    let d = pack_dir(id);
    if d.exists() {
        fs::remove_dir_all(d)?;
    }
    Ok(())
}

fn is_url(s: &str) -> bool {
    s.starts_with("http://") || s.starts_with("https://")
}

pub fn registry_source() -> String {
    std::env::var("PMAN_REGISTRY").unwrap_or_else(|_| DEFAULT_REGISTRY.to_string())
}

pub fn fetch_registry() -> Result<Registry, String> {
    let src = registry_source();
    let text = if is_url(&src) {
        ureq::get(&src)
            .timeout(Duration::from_secs(15))
            .call()
            .map_err(|e| format!("cannot reach the pack registry ({e})"))?
            .into_string()
            .map_err(|e| e.to_string())?
    } else {
        fs::read_to_string(&src).map_err(|e| format!("cannot read registry {src}: {e}"))?
    };
    serde_json::from_str(&text).map_err(|e| format!("bad registry: {e}"))
}

/// A pack's download URL; relative URLs and plain paths resolve against the registry location.
fn resolve(info: &PackInfo) -> String {
    if is_url(&info.url) || Path::new(&info.url).is_absolute() {
        return info.url.clone();
    }
    let src = registry_source();
    match src.rfind(|c| c == '/' || c == '\\') {
        Some(i) => format!("{}{}", &src[..=i], info.url),
        None => info.url.clone(),
    }
}

/// Removes interrupted installs: leftover unzip folders and download files older than a week.
pub fn clean_stale() {
    let Ok(rd) = fs::read_dir(packs_dir()) else { return };
    for e in rd.flatten() {
        let n = e.file_name().to_string_lossy().to_string();
        if n.ends_with(".tmp") {
            let _ = fs::remove_dir_all(e.path());
        } else if n.ends_with(".zip.part") {
            let old = e
                .metadata()
                .and_then(|m| m.modified())
                .ok()
                .and_then(|t| SystemTime::now().duration_since(t).ok())
                .map_or(false, |a| a > STALE_PART);
            if old {
                let _ = fs::remove_file(e.path());
            }
        }
    }
}

pub fn install(id: &str, info: &PackInfo, quiet: bool) -> Result<(), String> {
    let root = packs_dir();
    fs::create_dir_all(&root).map_err(|e| format!("cannot create {}: {e}", root.display()))?;
    clean_stale();
    let part = root.join(format!("{id}.zip.part"));
    let tmp = root.join(format!("{id}.tmp"));
    let url = resolve(info);

    let have = fs::metadata(&part).map(|m| m.len()).unwrap_or(0);
    let have = if have > info.size {
        let _ = fs::remove_file(&part);
        0
    } else {
        have
    };
    if have < info.size {
        download(&url, &part, have, info.size, quiet)?;
    }

    let sum = sha256_file(&part).map_err(|e| e.to_string())?;
    if fs::metadata(&part).map(|m| m.len()).unwrap_or(0) != info.size || !sum.eq_ignore_ascii_case(&info.sha256) {
        let _ = fs::remove_file(&part); // resuming a corrupt file would fail the same way
        return Err("download was corrupted, try again".into());
    }

    let _ = fs::remove_dir_all(&tmp);
    if let Err(e) = unzip(&part, &tmp) {
        let _ = fs::remove_dir_all(&tmp);
        return Err(e);
    }
    if let Err(e) = crate::index::build_bundle(&tmp) {
        let _ = fs::remove_dir_all(&tmp);
        return Err(format!("cannot index pack: {e}"));
    }
    fs::write(tmp.join(".version"), info.version.to_string()).map_err(|e| e.to_string())?;
    let dest = pack_dir(id);
    let _ = fs::remove_dir_all(&dest);
    fs::rename(&tmp, &dest).map_err(|e| format!("cannot install into {}: {e}", dest.display()))?;
    let _ = fs::remove_file(&part);
    Ok(())
}

fn download(url: &str, part: &Path, have: u64, total: u64, quiet: bool) -> Result<(), String> {
    let mut out_file;
    let mut reader: Box<dyn Read>;
    let mut done: u64;
    if is_url(url) {
        let mut req = ureq::get(url).timeout(Duration::from_secs(600));
        if have > 0 {
            req = req.set("Range", &format!("bytes={have}-"));
        }
        let resp = req.call().map_err(|e| match e {
            ureq::Error::Status(404, _) => "download not available yet (HTTP 404)".to_string(),
            ureq::Error::Status(c, _) => format!("server error (HTTP {c})"),
            _ => "no connection, nothing was installed".to_string(),
        })?;
        let resumed = resp.status() == 206;
        done = if resumed { have } else { 0 }; // a plain 200 ignored Range: restart from zero
        out_file = fs::OpenOptions::new()
            .create(true)
            .write(true)
            .append(resumed)
            .truncate(!resumed)
            .open(part)
            .map_err(|e| e.to_string())?;
        reader = Box::new(resp.into_reader());
    } else {
        let path = url.strip_prefix("file://").unwrap_or(url);
        reader = Box::new(File::open(path).map_err(|e| format!("cannot read {path}: {e}"))?);
        out_file = File::create(part).map_err(|e| e.to_string())?;
        done = 0;
    }
    let mut buf = [0u8; 32 * 1024];
    let mut last = 0u64;
    loop {
        let n = reader.read(&mut buf).map_err(|_| "connection lost; run the command again to resume".to_string())?;
        if n == 0 {
            break;
        }
        out_file.write_all(&buf[..n]).map_err(|e| e.to_string())?;
        done += n as u64;
        if !quiet && done - last >= 64 * 1024 {
            last = done;
            progress(done, total);
        }
    }
    if !quiet {
        progress(done, total);
        eprintln!();
    }
    Ok(())
}

fn progress(done: u64, total: u64) {
    let pct = if total > 0 { done * 100 / total } else { 0 };
    eprint!("\r  downloading {:.1} / {:.1} MB  {pct}%   ", done as f64 / 1048576.0, total as f64 / 1048576.0);
}

fn unzip(zip: &Path, dest: &Path) -> Result<(), String> {
    let mut archive = zip::ZipArchive::new(File::open(zip).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    for i in 0..archive.len() {
        let mut f = archive.by_index(i).map_err(|e| e.to_string())?;
        let Some(rel) = f.enclosed_name() else { return Err(format!("bad entry {}", f.name())) };
        let out = dest.join(rel);
        if f.is_dir() {
            fs::create_dir_all(&out).map_err(|e| e.to_string())?;
            continue;
        }
        if let Some(parent) = out.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut o = File::create(&out).map_err(|e| e.to_string())?;
        io::copy(&mut f, &mut o).map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn sha256_file(path: &Path) -> io::Result<String> {
    let mut f = File::open(path)?;
    let mut h = Sha256::new();
    let mut buf = [0u8; 64 * 1024];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(h.finalize().iter().map(|b| format!("{b:02x}")).collect())
}
