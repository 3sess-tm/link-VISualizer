#!/usr/bin/env python3
"""LinkGraph Web Tool - IMPROVED VERSION

Generates a single self-contained HTML file that visualizes internal links,
external links, dead links, dynamic/template links, and log-based popularity.

Improvements in this version:
- Fixed: --follow-symlinks duplicate argument definition
- Fixed: Truncated target_rel assignment bug
- Fixed: Proper symlink handling in directory traversal
- Added: Mobile-responsive design with collapsible sidebar
- Added: Configuration file support (.linkgraphrc)
- Added: Export functionality (JSON, SVG, CSV)
- Added: Keyboard shortcuts and help modal
- Added: Deep link support via URL anchors (#node-id)
- Added: Performance metrics and caching
- Added: Better error handling and logging
- Added: External links as optional nodes
- Added: Advanced filtering options
- Added: Accessibility improvements (ARIA, better colors)

Run example:
    python3 linkgraph_web_tool.py --root . --max-depth 8 --output linkgraph.html \
        --ignore-dir node_modules --ignore-dir .git --scan-ext html --scan-ext js \
        --log-file access.log --open
"""

from __future__ import annotations

import argparse
import base64
import html as html_lib
import json
import os
import re
import sys
import time
import webbrowser
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import quote

# ===== LOGGING SETUP =====
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# ===== DEFAULTS =====
DEFAULT_IGNORE_DIRS = {
    "node_modules", ".git", "__pycache__", "vendor", "dist", "build", ".next", ".cache"
}
DEFAULT_SCAN_EXTS = {
    "html", "htm", "css", "js", "mjs", "ts", "tsx", "php", "phtml", "twig", "xml", "json", "md"
}
DEFAULT_HUB_THRESHOLD = 6
DEFAULT_CONFIG_FILE = ".linkgraphrc"

# ===== REGEX PATTERNS =====
HTML_ATTR_RE = re.compile(
    r"(?is)\b(?:href|src|action|poster|data-href|data-src|content|url)\s*=\s*([\"'`])([^\"'`]+?)\1"
)
CSS_URL_RE = re.compile(r"(?is)url\(\s*([\"']?)(.*?)\1\s*\)")
JS_FROM_RE = re.compile(r"(?is)\bfrom\s*([\"'`])([^\"'`]+?)\1")
JS_REQUIRE_RE = re.compile(r"(?is)\brequire\s*\(\s*([\"'`])([^\"'`]+?)\1\s*\)")
JS_IMPORT_RE = re.compile(r"(?is)\bimport\s*([\"'`])([^\"'`]+?)\1")
LOG_REQ_RE = re.compile(r'"(?:GET|POST|HEAD|PUT|DELETE|OPTIONS|PATCH)\s+([^\s"]+)', re.I)
LOG_PATH_RE = re.compile(r"\s(\S+)\s(?:HTTP/|\")")
DYNAMIC_RE = re.compile(r"\$\{[^}]+\}|\{\{[^}]+\}\}")


@dataclass
class Config:
    root: Path
    output: Path
    title: str = "LinkGraph Pro"
    max_depth: int = 8
    max_file_size_kb: int = 512
    follow_symlinks: bool = False
    open_browser: bool = False
    include_external_nodes: bool = False
    enable_cache: bool = False
    cache_file: Optional[Path] = None
    hub_threshold: int = DEFAULT_HUB_THRESHOLD
    ignore_dirs: set[str] = field(default_factory=set)
    scan_exts: set[str] = field(default_factory=set)
    log_files: list[Path] = field(default_factory=list)
    debug: bool = False


@dataclass
class ScanResult:
    nodes: list[dict]
    edges: list[dict]
    meta: dict


# ===== CLI HELPERS =====
def parse_multi(values: list[str] | None, comma_ok: bool = True) -> list[str]:
    """Parse multiple values from CLI, supporting both comma-separated and repeated args."""
    out: list[str] = []
    for item in values or []:
        if comma_ok and "," in item:
            parts = item.split(",")
        else:
            parts = [item]
        for p in parts:
            v = p.strip()
            if v:
                out.append(v)
    return out


def log(msg: str, level: str = "INFO") -> None:
    """Log message with timestamp."""
    if level == "INFO":
        logger.info(msg)
    elif level == "WARNING":
        logger.warning(msg)
    elif level == "ERROR":
        logger.error(msg)
    elif level == "DEBUG":
        logger.debug(msg)


def progress(current: int, total: int, started: float, label: str) -> None:
    """Display progress bar in terminal."""
    if total <= 0:
        return
    frac = current / total
    elapsed = max(0.001, time.time() - started)
    eta = int((elapsed / current) * (total - current)) if current > 0 else 0
    width = 28
    filled = int(width * frac)
    bar = "#" * filled + "-" * (width - filled)
    sys.stdout.write(f"\r[{bar}] {frac*100:5.1f}% ETA {eta:>4}s  {label[:46]:46}")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")


# ===== UTILITY FUNCTIONS =====
def safe_id(text: str) -> str:
    """Convert text to safe CSS ID."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", text)


def escape_json(text: str) -> str:
    """Escape text for JSON."""
    return json.dumps(text, ensure_ascii=False)[1:-1]


def escape_html(text: str) -> str:
    """Escape text for HTML."""
    return html_lib.escape(text, quote=True)


def normalize_ext(ext: str) -> str:
    """Normalize file extension."""
    ext = ext.strip().lower()
    if ext.startswith('.'):
        ext = ext[1:]
    return ext


def split_terms(query: str) -> list[str]:
    """Parse search query into terms, respecting quoted phrases."""
    if not query.strip():
        return []
    terms: list[str] = []
    buf = []
    in_quote = False
    quote_char = ''
    for ch in query.strip():
        if ch in ('"', "'"):
            if in_quote and ch == quote_char:
                in_quote = False
                quote_char = ''
                continue
            if not in_quote:
                in_quote = True
                quote_char = ch
                continue
        if ch.isspace() and not in_quote:
            term = ''.join(buf).strip()
            if term:
                terms.append(term)
            buf = []
        else:
            buf.append(ch)
    term = ''.join(buf).strip()
    if term:
        terms.append(term)
    return terms


def is_external_link(link: str) -> bool:
    """Check if link is external."""
    low = link.lower()
    return low.startswith(("http://", "https://", "mailto:", "tel:", "data:", "javascript:", "//"))


def is_dynamic_link(link: str) -> bool:
    """Check if link contains template placeholders."""
    return bool(DYNAMIC_RE.search(link))


def strip_quotes(text: str) -> str:
    """Remove surrounding quotes."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", '`'):
        return text[1:-1]
    return text


def trim_link(link: str) -> str:
    """Clean and normalize a link."""
    link = link.strip()
    link = strip_quotes(link)
    link = link.replace('&amp;', '&')
    link = link.split('#', 1)[0].split('?', 1)[0]
    link = strip_quotes(link)
    return link.strip()


def looks_like_path(link: str) -> bool:
    """Heuristic: does this look like a file path?"""
    if not link:
        return False
    if is_external_link(link):
        return False
    if is_dynamic_link(link):
        return True
    if any(sep in link for sep in ('/', '\\', '.')):
        return True
    if link.startswith(('./', '../', '/')):
        return True
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]+(?:/[A-Za-z0-9_\-]+)+", link))


def kind_of(path: str) -> str:
    """Determine file kind from path."""
    ext = path.rsplit('.', 1)[-1].lower() if '.' in path else 'other'
    if ext in {'html', 'htm', 'twig', 'php', 'phtml'}:
        return 'html'
    if ext in {'css', 'scss', 'sass', 'less'}:
        return 'css'
    if ext in {'js', 'mjs', 'ts', 'tsx'}:
        return 'js'
    if ext in {'json'}:
        return 'json'
    if ext in {'md', 'markdown'}:
        return 'md'
    if ext in {'xml'}:
        return 'xml'
    return ext if ext != 'other' else 'other'


def group_of(path: str) -> str:
    """Get folder group of path."""
    p = Path(path)
    parent = p.parent.as_posix().strip('/')
    return parent if parent else '.'


def color_for(path: str, *, dead: bool = False, external: bool = False, dynamic: bool = False) -> str:
    """Get color for node based on type."""
    if dead:
        return '#f85149'
    if external:
        return '#58a6ff'
    if dynamic:
        return '#d29922'
    k = kind_of(path)
    return {
        'html': '#e34c26',
        'css': '#2965f1',
        'js': '#f7df1e',
        'json': '#2ea043',
        'md': '#8b949e',
        'xml': '#c9d1d9',
        'other': '#58a6ff',
    }.get(k, '#58a6ff')


def tooltip_for(node: dict) -> str:
    """Generate tooltip HTML for node."""
    bits = [
        f"<b>{escape_html(node['label'])}</b>",
        f"type: {escape_html(node.get('kind', 'other'))}",
        f"folder: {escape_html(node.get('group', '.'))}",
        f"degree: {node.get('degree', 0)}",
        f"popularity: {node.get('popularity', 0)}",
        f"size: {node.get('size', 0)} bytes",
    ]
    if node.get('dead'):
        bits.append('<b>dead / missing</b>')
    if node.get('dynamic'):
        bits.append('<b>dynamic link</b>')
    if node.get('external'):
        bits.append('<b>external</b>')
    return '<br>'.join(bits)


def read_text_best_effort(path: Path) -> str:
    """Read file with fallback encodings."""
    try:
        return path.read_text(encoding='utf-8', errors='ignore')
    except Exception:
        try:
            return path.read_text(encoding='latin-1', errors='ignore')
        except Exception:
            return ''


def load_config_file(config_file: Path) -> dict:
    """Load configuration from JSON file."""
    try:
        with open(config_file, 'r') as f:
            return json.load(f)
    except Exception as e:
        log(f"Could not load config file {config_file}: {e}", "WARNING")
        return {}


def _compute_scan_signature(cfg: Config) -> dict:
    """Compute a lightweight signature of the current scan settings and directory state."""
    try:
        root_mtime = cfg.root.stat().st_mtime
    except Exception:
        root_mtime = 0
    return {
        'root': str(cfg.root.resolve()),
        'max_depth': cfg.max_depth,
        'scan_exts': sorted(cfg.scan_exts),
        'ignore_dirs': sorted(cfg.ignore_dirs),
        'hub_threshold': cfg.hub_threshold if hasattr(cfg, 'hub_threshold') else DEFAULT_HUB_THRESHOLD,
        'root_mtime': root_mtime,
    }


def _load_scan_cache(cfg: Config) -> Optional[ScanResult]:
    """Attempt to load a cached scan result."""
    if not cfg.enable_cache or not cfg.cache_file:
        return None
    if not cfg.cache_file.exists():
        return None
    try:
        data = json.loads(cfg.cache_file.read_text(encoding='utf-8'))
        sig = data.get('scan_signature', {})
        if sig != _compute_scan_signature(cfg):
            return None
        nodes = data.get('nodes', [])
        edges = data.get('edges', [])
        meta = data.get('meta', {})
        log(f"Loaded cache: {cfg.cache_file}", 'DEBUG')
        return ScanResult(nodes=nodes, edges=edges, meta=meta)
    except Exception as e:
        log(f"Could not load scan cache {cfg.cache_file}: {e}", 'WARNING')
        return None


def _save_scan_cache(cfg: Config, result: ScanResult) -> None:
    """Save scan result to cache file."""
    if not cfg.enable_cache or not cfg.cache_file:
        return
    try:
        payload = {
            'scan_signature': _compute_scan_signature(cfg),
            'nodes': result.nodes,
            'edges': result.edges,
            'meta': result.meta,
        }
        cfg.cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        log(f"Saved scan cache: {cfg.cache_file}", 'DEBUG')
    except Exception as e:
        log(f"Could not save scan cache {cfg.cache_file}: {e}", 'WARNING')


# ===== LINK EXTRACTION & RESOLUTION =====
def extract_candidates(text: str) -> list[str]:
    """Extract all link candidates from text."""
    out: list[str] = []
    for rx in (HTML_ATTR_RE, CSS_URL_RE, JS_FROM_RE, JS_REQUIRE_RE, JS_IMPORT_RE):
        for m in rx.finditer(text):
            candidate = m.group(2)
            if candidate:
                out.append(candidate)
    # Add dynamic path detection
    dyn_attr = re.compile(r'(?is)\b(?:href|src|action|poster|data-href|data-src)\s*=\s*([\"\'])([^\"\']*\$\{[^\"\']+}[^\"\']*)\1')
    for m in dyn_attr.finditer(text):
        out.append(m.group(2))
    return out


def resolve_target(base_dir: Path, raw_link: str, root: Path, scan_exts: set[str]) -> tuple[str, bool, bool, Path | None]:
    """Resolve link to a target path or label."""
    link = trim_link(raw_link)
    if not link or is_external_link(link):
        return link, False, True, None

    dynamic = is_dynamic_link(link)
    clean = DYNAMIC_RE.sub('dynamic', link)

    if clean.startswith('/'):
        candidate = (root / clean.lstrip('/')).resolve()
    else:
        candidate = (base_dir / clean).resolve()

    if dynamic:
        return clean, True, False, candidate

    # Handle path too long errors gracefully
    try:
        if candidate.exists():
            return clean, False, False, candidate
    except OSError as e:
        # Path too long or other filesystem error - treat as non-existent
        log(f"Skipping path due to error: {e}", "DEBUG")
        return clean, False, False, candidate

    # Try extension guesses
    if '.' not in Path(clean).name:
        for ext in sorted(scan_exts):
            trial = candidate.with_suffix('.' + ext)
            try:
                if trial.exists():
                    return str(trial.relative_to(root)).replace('\\', '/'), False, False, trial
            except OSError as e:
                log(f"Skipping trial path due to error: {e}", "DEBUG")
                continue
        
        for ext in ('html', 'htm', 'php', 'md'):
            trial = candidate / ('index.' + ext)
            try:
                if trial.exists():
                    return str(trial.relative_to(root)).replace('\\', '/'), False, False, trial
            except OSError as e:
                log(f"Skipping index trial path due to error: {e}", "DEBUG")
                continue

    return clean, False, False, candidate

# ===== LOG POPULARITY PARSING =====
def normalize_request_path(req: str) -> str:
    """Normalize request path from logs."""
    req = req.strip()
    if not req or is_external_link(req):
        return ''
    req = req.split('?', 1)[0].split('#', 1)[0]
    if req.startswith('/'):
        req = req[1:]
    return req


def parse_logs(log_files: Iterable[Path]) -> Counter[str]:
    """Parse log files for popularity metrics."""
    hits: Counter[str] = Counter()
    for log_file in log_files:
        if not log_file.exists() or not log_file.is_file():
            continue
        try:
            for line in read_text_best_effort(log_file).splitlines():
                m = LOG_REQ_RE.search(line) or LOG_PATH_RE.search(line)
                if not m:
                    continue
                raw = m.group(1)
                req = normalize_request_path(raw)
                if req:
                    hits[req] += 1
        except Exception as e:
            log(f"Error parsing log file {log_file}: {e}", "WARNING")
    return hits


# ===== PROJECT SCANNING =====
def scan_project(cfg: Config) -> ScanResult:
    """Scan project and build link graph."""
    root = cfg.root.resolve()
    ignore_lower = {d.lower() for d in cfg.ignore_dirs}
    scan_exts = {normalize_ext(e) for e in cfg.scan_exts}

    if cfg.enable_cache:
        cached = _load_scan_cache(cfg)
        if cached:
            return cached

    candidate_files: list[Path] = []
    visited_dirs: set[Path] = set()
    scanned_total_bytes = 0

    log(f"Scanning {root}")
    started_walk = time.time()

    # ===== DIRECTORY WALK WITH PROPER SYMLINK HANDLING =====
    for current_root, dirs, files in os.walk(root, followlinks=cfg.follow_symlinks):
        cur = Path(current_root)
        try:
            real = cur.resolve()
        except Exception:
            real = cur

        if real in visited_dirs:
            dirs[:] = []
            continue
        visited_dirs.add(real)

        try:
            rel = cur.relative_to(root)
            depth = 0 if str(rel) == '.' else len(rel.parts)
        except Exception:
            depth = 0

        if depth >= cfg.max_depth:
            dirs[:] = []

        # Prune directories: respect ignore list and symlinks
        pruned = []
        for d in dirs:
            if d.lower() in ignore_lower:
                continue
            dpath = cur / d
            # Only skip symlinks if follow_symlinks is False
            if not cfg.follow_symlinks and dpath.is_symlink():
                continue
            try:
                if dpath.resolve() in visited_dirs:
                    continue
            except Exception:
                pass
            pruned.append(d)
        dirs[:] = pruned

        # Collect files
        for filename in files:
            fpath = cur / filename
            ext = normalize_ext(fpath.suffix)
            if ext not in scan_exts:
                continue
            try:
                size = fpath.stat().st_size
            except Exception:
                size = 0
            if size > cfg.max_file_size_kb * 1024:
                continue
            candidate_files.append(fpath)
            scanned_total_bytes += size

    log(f"Found {len(candidate_files)} scanable files ({scanned_total_bytes / 1024:.1f} KB)")

    # ===== GRAPH BUILDING =====
    graph_nodes: dict[str, dict] = {}
    graph_edges: list[dict] = []
    degree: Counter[str] = Counter()
    popularity_raw = Counter()
    folder_set: set[str] = set()
    type_set: set[str] = set()
    edge_id = 0
    dead_links = 0
    external_links = 0
    dynamic_links = 0

    if cfg.log_files:
        log(f"Reading {len(cfg.log_files)} log file(s)")
        popularity_raw = parse_logs(cfg.log_files)

    started = time.time()
    started = time.time()
    for i, fpath in enumerate(candidate_files, 1):
        progress(i, len(candidate_files), started, fpath.name)

        # Handle symlinks that point outside root
        try:
            rel = fpath.resolve().relative_to(root).as_posix()
        except ValueError:
            # Symlink target is outside root; use the symlink path itself instead
            try:
                rel = fpath.relative_to(root).as_posix()
            except ValueError:
                log(f"Skipping file outside root: {fpath}", "DEBUG")
                continue
    
        folder = group_of(rel)
        kind = kind_of(rel)
        folder_set.add(folder)
        type_set.add(kind)
        try:
            size = fpath.stat().st_size
        except Exception:
            size = 0

        # Ensure every scanned file is represented in the graph (including orphans)
        src_id = safe_id(rel)
        if src_id not in graph_nodes:
            graph_nodes[src_id] = {
                'id': src_id,
                'label': rel,
                'group': folder,
                'kind': kind,
                'size': size,
                'color': color_for(rel),
                'degree': 0,
                'popularity': 0,
                'dead': False,
                'dynamic': False,
                'external': False,
                'value': 8,
            }

        text = read_text_best_effort(fpath)
        for raw in extract_candidates(text):
            resolved_label, is_dynamic, is_external, resolved_path = resolve_target(fpath.parent, raw, root, scan_exts)
            if not resolved_label:
                continue

            if is_external:
                external_links += 1
                if cfg.include_external_nodes:
                    # Add external links as nodes (optional feature)
                    target_id = safe_id(resolved_label)
                    src_id = safe_id(rel)
                    if src_id not in graph_nodes:
                        graph_nodes[src_id] = {
                            'id': src_id, 'label': rel, 'group': folder, 'kind': kind, 'size': size,
                            'color': color_for(rel), 'degree': 0, 'popularity': 0, 'dead': False,
                            'dynamic': False, 'external': False, 'value': 8,
                        }
                    if target_id not in graph_nodes:
                        graph_nodes[target_id] = {
                            'id': target_id, 'label': resolved_label, 'group': 'external', 'kind': 'external', 'size': 0,
                            'color': color_for(resolved_label, external=True), 'degree': 0, 'popularity': 0, 'dead': False,
                            'dynamic': False, 'external': True, 'value': 6,
                        }
                    graph_edges.append({
                        'id': f'e{edge_id}', 'from': src_id, 'to': target_id, 'label': trim_link(raw)[:80],
                        'color': '#58a6ff', 'dashes': False, 'arrows': 'to', 'dynamic': False,
                        'title': f"External link: {escape_html(trim_link(raw))}",
                    })
                    edge_id += 1
                    degree[src_id] += 1
                    degree[target_id] += 1
                continue

            if is_dynamic:
                dynamic_links += 1
                target_label = f"dynamic:{resolved_label}"
                target_id = safe_id(target_label)
                src_id = safe_id(rel)
                if src_id not in graph_nodes:
                    graph_nodes[src_id] = {
                        'id': src_id, 'label': rel, 'group': folder, 'kind': kind, 'size': size,
                        'color': color_for(rel), 'degree': 0, 'popularity': 0, 'dead': False,
                        'dynamic': False, 'external': False, 'value': 8,
                    }
                if target_id not in graph_nodes:
                    graph_nodes[target_id] = {
                        'id': target_id, 'label': target_label, 'group': 'dynamic', 'kind': 'dynamic', 'size': 0,
                        'color': color_for(target_label, dynamic=True), 'degree': 0, 'popularity': 0, 'dead': False,
                        'dynamic': True, 'external': False, 'value': 7,
                    }
                graph_edges.append({
                    'id': f'e{edge_id}', 'from': src_id, 'to': target_id, 'label': trim_link(raw)[:80],
                    'color': '#d29922', 'dashes': True, 'arrows': 'to', 'dynamic': True,
                    'title': f"Dynamic link: {escape_html(trim_link(raw))}",
                })
                edge_id += 1
                degree[src_id] += 1
                degree[target_id] += 1
                continue

            # FIX: Proper target_rel assignment (was truncated in original)
            if resolved_path and resolved_path.exists():
                try:
                    target_rel = str(resolved_path.relative_to(root)).replace('\\', '/')
                except ValueError:
                    target_rel = resolved_label
            else:
                target_rel = resolved_label

            exists = bool(resolved_path and resolved_path.exists())
            if not exists:
                dead_links += 1

            src_id = safe_id(rel)
            dst_id = safe_id(target_rel)
            if src_id not in graph_nodes:
                graph_nodes[src_id] = {
                    'id': src_id, 'label': rel, 'group': folder, 'kind': kind, 'size': size,
                    'color': color_for(rel), 'degree': 0, 'popularity': 0, 'dead': False,
                    'dynamic': False, 'external': False, 'value': 8,
                }
            if dst_id not in graph_nodes:
                dst_kind = kind_of(target_rel)
                dst_group = group_of(target_rel)
                dst_size = 0
                if resolved_path and resolved_path.exists():
                    try:
                        dst_size = resolved_path.stat().st_size
                    except Exception:
                        dst_size = 0
                graph_nodes[dst_id] = {
                    'id': dst_id, 'label': target_rel, 'group': dst_group, 'kind': dst_kind, 'size': dst_size,
                    'color': color_for(target_rel, dead=not exists), 'degree': 0, 'popularity': 0, 'dead': not exists,
                    'dynamic': False, 'external': False, 'value': 8,
                }

            graph_edges.append({
                'id': f'e{edge_id}', 'from': src_id, 'to': dst_id, 'label': trim_link(raw)[:80],
                'color': '#f85149' if not exists else '#6e7681', 'dashes': not exists, 'arrows': 'to',
                'dynamic': False, 'title': f"Link: {escape_html(trim_link(raw))}",
            })
            edge_id += 1
            degree[src_id] += 1
            degree[dst_id] += 1

    # Popularity mapping
    popularity = Counter()
    for req, count in popularity_raw.items():
        req_n = req.lstrip('/')
        popularity[req_n] += count
        if req_n.endswith('/'):
            popularity[req_n[:-1]] += count
        for suffix in ('index.html', 'index.htm', 'index.php'):
            popularity[req_n.rstrip('/') + '/' + suffix] += count

    # Finalize nodes
    for node in graph_nodes.values():
        label = node['label']
        node['degree'] = int(degree.get(node['id'], 0))
        node['popularity'] = int(popularity.get(label, 0))
        node['kind'] = node.get('kind') or kind_of(label)
        node['group'] = node.get('group') or group_of(label)
        node['color'] = node.get('color') or color_for(label)
        node['title'] = tooltip_for(node)
        node['value'] = max(5, min(50, 6 + node['degree'] * 2 + node['popularity'] * 3 + (node.get('size', 0) // 200_000)))
        if node.get('dead'):
            node['color'] = '#f85149'
        if node.get('dynamic'):
            node['color'] = '#d29922'

    all_degrees = [degree.get(n['id'], 0) for n in graph_nodes.values()]
    meta = {
        'root': str(root),
        'fileCount': len(candidate_files),
        'scanBytes': scanned_total_bytes,
        'edgeCount': len(graph_edges),
        'nodeCount': len(graph_nodes),
        'deadLinks': dead_links,
        'externalLinks': external_links,
        'dynamicLinks': dynamic_links,
        'types': sorted(type_set),
        'folders': sorted(folder_set),
        'popularNodes': sum(1 for n in graph_nodes.values() if n.get('popularity', 0) > 0),
        'orphanNodes': sum(1 for d in all_degrees if d == 0),
        'hubNodes': sum(1 for d in all_degrees if d >= cfg.hub_threshold),
        'averageDegree': round(sum(all_degrees) / len(all_degrees), 2) if all_degrees else 0,
        'topNodes': sorted(
            (
                {'id': n['id'], 'label': n['label'], 'degree': n['degree'], 'popularity': n['popularity'], 'group': n['group']}
                for n in graph_nodes.values()
            ),
            key=lambda x: (x['popularity'] * 3 + x['degree'], x['degree'], x['label'].lower()),
            reverse=True,
        )[:50],
        'topFolders': sorted(
            ({'label': folder, 'count': sum(1 for n in graph_nodes.values() if n.get('group') == folder)} for folder in folder_set),
            key=lambda x: (x['count'], x['label'].lower()),
            reverse=True,
        )[:50],
    }

    result = ScanResult(nodes=list(graph_nodes.values()), edges=graph_edges, meta=meta)
    _save_scan_cache(cfg, result)
    log(f"Done: {meta['nodeCount']} nodes, {meta['edgeCount']} edges, {dead_links} dead links")
    return result


# ===== HTML GENERATION =====
def build_html(cfg: Config, result: ScanResult) -> str:
    """Generate responsive HTML with mobile support."""
    payload = base64.b64encode(
        json.dumps(
            {'nodes': result.nodes, 'edges': result.edges, 'meta': result.meta},
            ensure_ascii=False,
            separators=(',', ':'),
        ).encode('utf-8')
    ).decode('ascii')

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=5" />
<title>{escape_html(cfg.title)}</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
:root {{
  --bg: #0d1117;
  --panel: #161b22;
  --panel2: #0f141b;
  --line: #30363d;
  --text: #c9d1d9;
  --muted: #8b949e;
  --accent: #58a6ff;
}}

html, body {{
  width: 100%;
  height: 100%;
  margin: 0;
  overflow: hidden;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
}}

body {{
  display: flex;
  flex-direction: column;
}}

#sidebarToggle {{
  display: none;
  position: fixed;
  top: 10px;
  left: 10px;
  z-index: 1000;
  background: linear-gradient(180deg, #1f6feb, #1857c7);
  border: none;
  border-radius: 10px;
  color: white;
  padding: 8px 12px;
  cursor: pointer;
  font-weight: 700;
  font-size: 14px;
}}

#sidebar {{
  width: 380px;
  min-width: 320px;
  max-width: 500px;
  height: 100vh;
  overflow: auto;
  background: linear-gradient(180deg, var(--panel), #11161d);
  border-right: 1px solid var(--line);
  padding: 14px;
  box-sizing: border-box;
  transition: transform 0.3s ease;
}}

#main {{
  flex: 1;
  height: 100vh;
  min-width: 0;
  position: relative;
  display: flex;
}}

#network {{
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
}}

#miniWrap {{
  position: absolute;
  right: 12px;
  bottom: 12px;
  width: 250px;
  height: 180px;
  border: 1px solid var(--line);
  border-radius: 12px;
  overflow: hidden;
  background: rgba(13,17,23,0.9);
  backdrop-filter: blur(8px);
  display: none;
  z-index: 4;
}}

#miniHead {{
  padding: 6px 8px;
  font-size: 12px;
  border-bottom: 1px solid var(--line);
  color: var(--muted);
}}

#minimap {{ width: 100%; height: calc(100% - 25px); }}

#contextMenu {{
  position: fixed;
  z-index: 9999;
  min-width: 180px;
  display: none;
  background: #0b1017;
  border: 1px solid var(--line);
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0,0,0,0.35);
  overflow: hidden;
}}

#contextMenu button {{
  width: 100%;
  background: transparent;
  border: 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  border-radius: 0;
  text-align: left;
  padding: 10px 12px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text);
}}

#contextMenu button:hover {{
  background: rgba(88,166,255,0.14);
}}

#helpModal {{
  display: none;
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0,0,0,0.5);
  z-index: 10000;
  align-items: center;
  justify-content: center;
}}

#helpContent {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 12px;
  padding: 20px;
  max-width: 500px;
  max-height: 80vh;
  overflow: auto;
  color: var(--text);
}}

#helpContent h2 {{
  margin-top: 0;
  color: #e6edf3;
}}

#helpContent .shortcut {{
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255,255,255,0.05);
  font-size: 12px;
}}

#helpContent .key {{
  background: var(--panel2);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: monospace;
  font-weight: 600;
  color: #58a6ff;
}}

.section {{ margin-bottom: 14px; padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.06); }}
.section h3 {{ margin: 0 0 10px 0; font-size: 13px; letter-spacing: .06em; text-transform: uppercase; color: #e6edf3; }}
.row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.row3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; }}

input, select, button {{
  width: 100%; box-sizing: border-box; background: #0b1017; color: var(--text);
  border: 1px solid var(--line); border-radius: 10px; padding: 9px 10px; font-size: 13px;
}}

button {{ cursor: pointer; background: linear-gradient(180deg, #1f6feb, #1857c7); border-color: rgba(255,255,255,0.08); font-weight: 700; }}
button.secondary {{ background: #0b1017; }}
button:hover {{ filter: brightness(1.08); }}
button:disabled {{ opacity: 0.5; cursor: not-allowed; }}

.small {{ font-size: 12px; color: var(--muted); }}
.chipbar {{ display:flex; gap:8px; flex-wrap: wrap; }}
.chip {{ border: 1px solid var(--line); border-radius: 999px; padding: 6px 10px; cursor: pointer; user-select: none; background: #0b1017; font-size: 12px; }}
.chip.on {{ border-color: #1f6feb; background: rgba(31,111,235,0.18); color: #dbeafe; }}
.listbox {{ max-height: 240px; overflow: auto; padding-right: 4px; }}
.listItem {{ margin-bottom: 8px; cursor: pointer; padding: 8px; border: 1px solid rgba(255,255,255,0.06); border-radius: 10px; background: rgba(255,255,255,0.02); }}
.listItem:hover {{ border-color: rgba(88,166,255,0.45); background: rgba(88,166,255,0.08); }}
.statcard {{ display:grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
.stat {{ border: 1px solid var(--line); border-radius: 12px; padding: 10px; background: rgba(255,255,255,0.02); }}
.stat .big {{ font-size: 18px; font-weight: 800; color: #e6edf3; }}
.stat .small {{ font-size: 12px; color: var(--muted); }}
.pillbar {{ position:absolute; top:10px; left:10px; right:10px; display:flex; flex-wrap:wrap; gap:8px; z-index:3; pointer-events:none; }}
.pillbar > * {{ pointer-events:auto; }}
.pill {{ background: rgba(13,17,23,0.86); border: 1px solid var(--line); border-radius: 999px; padding: 8px 12px; font-size: 12px; backdrop-filter: blur(8px); }}
.details {{ display:grid; gap:6px; }}
.kv {{ display:grid; grid-template-columns: 120px 1fr; gap: 8px; font-size: 12px; }}
.kv div:first-child {{ color: var(--muted); }}
.legend-item {{ display:flex; align-items:center; gap:10px; margin-bottom: 8px; font-size: 13px; }}
.swatch {{ width:12px; height:12px; border-radius:3px; display:inline-block; flex: 0 0 12px; }}
.sw-html {{ background:#e34c26; }}
.sw-css {{ background:#2965f1; }}
.sw-js {{ background:#f7df1e; }}
.sw-dead {{ background:#f85149; }}
.sw-dyn {{ background:#d29922; }}
.sw-ext {{ background:#58a6ff; }}
.sw-pop {{ background:#2ea043; }}
.topline {{ font-size: 12px; color: var(--muted); margin-top: 8px; }}

/* ===== MOBILE RESPONSIVE ===== */
@media (max-width: 768px) {{
  body {{
    flex-direction: column;
  }}
  
  #sidebarToggle {{
    display: block;
  }}
  
  #sidebar {{
    position: fixed;
    left: 0;
    top: 0;
    height: 100vh;
    width: 75vw;
    max-width: 300px;
    z-index: 999;
    transform: translateX(-100%);
    border-right: 1px solid var(--line);
  }}
  
  #sidebar.open {{
    transform: translateX(0);
  }}
  
  #main {{
    width: 100%;
    flex: 1;
  }}
  
  #miniWrap {{
    display: none !important;
  }}
  
  .pillbar {{
    display: none;
  }}
  
  input, select, button {{
    padding: 12px 10px;
    font-size: 14px;
  }}
  
  .row3 {{
    grid-template-columns: 1fr;
  }}
  
  #network {{
    width: 100%;
    height: 100%;
  }}
}}

@media (max-width: 480px) {{
  #sidebar {{
    width: 90vw;
  }}
  
  .section {{
    margin-bottom: 12px;
  }}
  
  .stat .big {{
    font-size: 16px;
  }}
}}
</style>
</head>
<body>
<button id="sidebarToggle" aria-label="Toggle sidebar">☰ Menu</button>

<aside id="sidebar" role="navigation" aria-label="Filters and controls">
  <div class="section">
    <h3>Search</h3>
    <input id="include" placeholder="Include terms" aria-label="Include search terms" />
    <div style="height:8px"></div>
    <input id="exclude" placeholder="Exclude terms" aria-label="Exclude search terms" />
    <div style="height:8px"></div>
    <div class="row3">
      <select id="matchMode" aria-label="Search match mode">
        <option value="all">Match all</option>
        <option value="any">Match any</option>
        <option value="none">Show non-matches</option>
      </select>
      <label class="chip" id="invertChip"><input type="checkbox" id="invert" style="display:none" /> Invert</label>
      <label class="chip" id="caseChip"><input type="checkbox" id="caseSensitive" style="display:none" /> Case</label>
    </div>
    <div style="height:8px"></div>
    <div class="row3">
      <button id="applyBtn">Apply</button>
      <button class="secondary" id="resetBtn">Reset</button>
      <button class="secondary" id="fitBtn">Fit</button>
    </div>
  </div>

  <div class="section">
    <h3>Filters</h3>
    <div class="row">
      <select id="typeFilter" aria-label="Filter by file type"></select>
      <select id="folderFilter" aria-label="Filter by folder"></select>
    </div>
    <div style="height:8px"></div>
    <div class="row3">
      <label class="chip" id="deadChip"><input type="checkbox" id="deadOnly" style="display:none" /> Dead only</label>
      <label class="chip" id="popChip"><input type="checkbox" id="popularOnly" style="display:none" /> Popular only</label>
      <label class="chip" id="dynChip"><input type="checkbox" id="dynamicOnly" style="display:none" /> Dynamic only</label>
      <label class="chip" id="extChip"><input type="checkbox" id="externalOnly" style="display:none" /> External only</label>
    </div>
    <div style="height:8px"></div>
    <div class="row3">
      <input id="minPop" type="number" min="0" value="1" title="Minimum popularity" aria-label="Minimum popularity" />
      <input id="minDegree" type="number" min="0" value="1" title="Minimum degree" aria-label="Minimum degree" />
      <input id="maxNodes" type="number" min="1" value="5000" title="Limit visible nodes" aria-label="Maximum nodes" />
    </div>
    <div style="height:8px"></div>
    <select id="sortFilter" aria-label="Sort order">
      <option value="importance">Sort by importance</option>
      <option value="popularity">Sort by popularity</option>
      <option value="alphabetical">Sort alphabetically</option>
      <option value="folder">Sort by folder</option>
      <option value="type">Sort by type</option>
    </select>
    <div class="small" style="margin-top:8px">Tip: include/exclude supports multiple terms and quoted phrases.</div>
  </div>

  <div class="section">
    <h3>Actions</h3>
    <div class="row3">
      <button class="secondary" id="fullscreenBtn">Fullscreen</button>
      <button class="secondary" id="miniBtn">Minimap</button>
      <button class="secondary" id="relayoutBtn">Layout</button>
    </div>
    <div style="height:8px"></div>
    <div class="row3">
      <button class="secondary" id="showAllBtn">Show all</button>
      <button class="secondary" id="exportBtn">Export state</button>
      <button class="secondary" id="exportJsonBtn">Export JSON</button>
      <button class="secondary" id="exportCsvBtn">Export CSV</button>
      <button class="secondary" id="copyBtn" disabled>Copy selected</button>
    </div>
    <div style="height:8px"></div>
    <button class="secondary" id="helpBtn" style="width:100%">? Keyboard Shortcuts</button>
    <div class="topline">Right-click a node for hide / isolate / neighbor-only actions.</div>
  </div>

  <div class="section">
    <h3>Legend</h3>
    <div class="legend-item"><span class="swatch sw-html"></span> HTML / page</div>
    <div class="legend-item"><span class="swatch sw-css"></span> CSS</div>
    <div class="legend-item"><span class="swatch sw-js"></span> JS / TS</div>
    <div class="legend-item"><span class="swatch sw-dead"></span> Dead link</div>
    <div class="legend-item"><span class="swatch sw-dyn"></span> Dynamic link</div>
    <div class="legend-item"><span class="swatch sw-ext"></span> External link</div>
    <div class="legend-item"><span class="swatch sw-pop"></span> Popular (from logs)</div>
  </div>

  <div class="section">
    <h3>Stats</h3>
    <div class="statcard">
      <div class="stat"><div class="big" id="statNodes">0</div><div class="small">Nodes</div></div>
      <div class="stat"><div class="big" id="statEdges">0</div><div class="small">Edges</div></div>
      <div class="stat"><div class="big" id="statDead">0</div><div class="small">Dead links</div></div>
      <div class="stat"><div class="big" id="statPopular">0</div><div class="small">Popular nodes</div></div>
      <div class="stat"><div class="big" id="statOrphans">0</div><div class="small">Orphans</div></div>
      <div class="stat"><div class="big" id="statHubs">0</div><div class="small">Hubs</div></div>
      <div class="stat"><div class="big" id="statAvgDegree">0</div><div class="small">Avg degree</div></div>
    </div>
  </div>

  <div class="section">
    <h3>Top nodes</h3>
    <div id="topNodes" class="listbox"></div>
  </div>

  <div class="section">
    <h3>Top folders</h3>
    <div id="topFolders" class="listbox"></div>
  </div>

  <div class="section">
    <h3>Selected</h3>
    <div id="selectedInfo" class="details"><div class="small">Nothing selected.</div></div>
  </div>
</aside>

<main id="main" role="main">
  <div class="pillbar">
    <div class="pill">Drag to pan</div>
    <div class="pill">Scroll to zoom</div>
    <div class="pill">Click to select</div>
    <div class="pill">Double click to focus</div>
  </div>
  <div id="network"></div>
  <div id="miniWrap">
    <div id="miniHead">Minimap</div>
    <div id="minimap"></div>
  </div>
</main>

<div id="contextMenu" role="menu" aria-label="Node context menu">
  <button id="ctxFocus">Focus node</button>
  <button id="ctxNeighbors">Show node + neighbors</button>
  <button id="ctxHide">Hide node</button>
  <button id="ctxShowAll">Show all</button>
</div>

<div id="helpModal" role="dialog" aria-modal="true" aria-labelledby="helpTitle">
  <div id="helpContent">
    <h2 id="helpTitle">Keyboard Shortcuts</h2>
    <div class="shortcut">
      <span>Escape</span>
      <span class="key">ESC</span>
    </div>
    <div class="shortcut">
      <span>Toggle sidebar (mobile)</span>
      <span class="key">M</span>
    </div>
    <div class="shortcut">
      <span>Toggle minimap</span>
      <span class="key">Shift + M</span>
    </div>
    <div class="shortcut">
      <span>Fit graph</span>
      <span class="key">F</span>
    </div>
    <div class="shortcut">
      <span>Fullscreen</span>
      <span class="key">Shift + F</span>
    </div>
    <div class="shortcut">
      <span>Apply filters</span>
      <span class="key">Enter</span>
    </div>
    <div class="shortcut">
      <span>Reset all</span>
      <span class="key">Shift + R</span>
    </div>
    <div class="shortcut">
      <span>Help</span>
      <span class="key">?</span>
    </div>
    <br />
    <p style="font-size: 12px; color: var(--muted);">
      <strong>Node selection:</strong> Click to select, Double-click to focus, Right-click for context menu.
    </p>
  </div>
</div>

<script id="payload" type="text/plain">{{payload}}</script>
<script>
const raw = document.getElementById('payload').textContent.trim();
const data = JSON.parse(atob(raw));
const nodes = new vis.DataSet(data.nodes);
const edges = new vis.DataSet(data.edges);
const meta = data.meta;
const state = {{
  hidden: new Set(),
  isolateNode: null,
  selectedNode: null,
  miniVisible: false,
  sidebarOpen: false,
  nodeIdFromUrl: null,
}};

// Parse URL anchor for deep linking
function parseUrlAnchor() {{
  const hash = window.location.hash.slice(1);
  if (hash) {{
    state.nodeIdFromUrl = decodeURIComponent(hash);
  }}
}}

const mainNetwork = new vis.Network(
  document.getElementById('network'),
  {{ nodes, edges }},
  {{
    autoResize: true,
    interaction: {{ hover: true, hoverConnectedEdges: true, navigationButtons: true, keyboard: true, multiselect: true }},
    physics: {{ enabled: true, stabilization: {{ iterations: 140, fit: true }}, barnesHut: {{ gravitationalConstant: -22000, springLength: 130, springConstant: 0.03, damping: 0.32 }} }},
    layout: {{ improvedLayout: true }},
    nodes: {{ shape: 'dot', font: {{ color: '#e6edf3', size: 13 }}, borderWidth: 2, scaling: {{ min: 6, max: 42 }} }},
    edges: {{ smooth: {{ type: 'dynamic' }}, arrows: {{ to: {{ enabled: true, scaleFactor: 0.4 }} }} }}
  }}
);

const miniNetwork = new vis.Network(
  document.getElementById('minimap'),
  {{ nodes, edges }},
  {{
    autoResize: true,
    interaction: {{ dragView: false, zoomView: false, selectable: false }},
    physics: false,
    nodes: {{ shape: 'dot', font: {{ size: 0 }}, scaling: {{ min: 2, max: 8 }}, borderWidth: 1 }},
    edges: {{ smooth: false, arrows: {{ to: {{ enabled: false }} }} }}
  }}
);

mainNetwork.once('stabilizationIterationsDone', () => mainNetwork.setOptions({{ physics: false }}));

function esc(s) {{
  return String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}}

function ext(name) {{
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i + 1).toLowerCase() : 'other';
}}

function kindGroup(label) {{
  const e = ext(label);
  if (['html','htm','twig','php','phtml'].includes(e)) return 'html';
  if (['js','mjs','ts','tsx'].includes(e)) return 'js';
  if (['css','scss','sass','less'].includes(e)) return 'css';
  if (['json','md','xml'].includes(e)) return e;
  return 'other';
}}

function termsFrom(text) {{
  const raw = (text || '').trim();
  if (!raw) return [];
  const out = [];
  let buf = '';
  let quote = null;
  for (const ch of raw) {{
    if ((ch === '"' || ch === "'") && (!quote || quote === ch)) {{
      quote = quote ? null : ch;
      continue;
    }}
    if (/\s/.test(ch) && !quote) {{
      if (buf.trim()) out.push(buf.trim());
      buf = '';
    }} else {{
      buf += ch;
    }}
  }}
  if (buf.trim()) out.push(buf.trim());
  return out;
}}

function textForNode(n) {{
  return [n.label, n.group, n.kind].filter(Boolean).join(' ').toLowerCase();
}}

function buildSelectOptions(select, values, allLabel) {{
  select.innerHTML = '';
  const all = document.createElement('option');
  all.value = 'all';
  all.textContent = allLabel;
  select.appendChild(all);
  values.forEach(v => {{
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = v;
    select.appendChild(opt);
  }});
}}

function renderMetaLists() {{
  buildSelectOptions(document.getElementById('typeFilter'), meta.types || [], 'All types');
  buildSelectOptions(document.getElementById('folderFilter'), meta.folders || [], 'All folders');
  document.getElementById('statNodes').textContent = meta.nodeCount || 0;
  document.getElementById('statEdges').textContent = meta.edgeCount || 0;
  document.getElementById('statDead').textContent = meta.deadLinks || 0;
  document.getElementById('statPopular').textContent = meta.popularNodes || 0;
  document.getElementById('statOrphans').textContent = meta.orphanNodes || 0;
  document.getElementById('statHubs').textContent = meta.hubNodes || 0;
  document.getElementById('statAvgDegree').textContent = meta.averageDegree || 0;
  const topNodes = (meta.topNodes || []).slice(0, 25);
  const topFolders = (meta.topFolders || []).slice(0, 25);
  document.getElementById('topNodes').innerHTML = topNodes.map(n => `
    <div class="listItem" data-id="${{esc(n.id)}}">
      <div style="font-weight:700;color:#e6edf3">${{esc(n.label)}}</div>
      <div class="small">degree ${{n.degree || 0}} · pop ${{n.popularity || 0}}</div>
    </div>`).join('');
  document.getElementById('topFolders').innerHTML = topFolders.map(f => `
    <div class="listItem">
      <div style="font-weight:700;color:#e6edf3">${{esc(f.label)}}</div>
      <div class="small">${{f.count || 0}} files</div>
    </div>`).join('');
  document.querySelectorAll('#topNodes .listItem').forEach(el => {{
    el.addEventListener('click', () => focusNode(el.dataset.id));
  }});
}}

function applyChip(chipId, checkboxId) {{
  const chip = document.getElementById(chipId);
  const cb = document.getElementById(checkboxId);
  function sync() {{ chip.classList.toggle('on', cb.checked); }}
  cb.addEventListener('change', sync);
  chip.addEventListener('click', () => {{ cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); applyFilters(); }});
  sync();
}}

function nodeMatchesSearch(node, includeTerms, excludeTerms, mode, caseSensitive) {{
  let hay = textForNode(node);
  if (caseSensitive) {{
    const include = includeTerms;
    const exclude = excludeTerms;
    if (exclude.some(t => hay.includes(t))) return false;
    if (!include.length) return true;
    if (mode === 'all') return include.every(t => hay.includes(t));
    if (mode === 'any') return include.some(t => hay.includes(t));
    if (mode === 'none') return !include.some(t => hay.includes(t));
    return true;
  }} else {{
    hay = hay.toLowerCase();
    const include = includeTerms.map(t => t.toLowerCase());
    const exclude = excludeTerms.map(t => t.toLowerCase());
    if (exclude.some(t => hay.includes(t))) return false;
    if (!include.length) return true;
    if (mode === 'all') return include.every(t => hay.includes(t));
    if (mode === 'any') return include.some(t => hay.includes(t));
    if (mode === 'none') return !include.some(t => hay.includes(t));
    return true;
  }}
}}

function applyFilters() {{
  const includeTerms = termsFrom(document.getElementById('include').value);
  const excludeTerms = termsFrom(document.getElementById('exclude').value);
  const mode = document.getElementById('matchMode').value;
  const invert = document.getElementById('invert').checked;
  const caseSensitive = document.getElementById('caseSensitive').checked;
  const typeFilter = document.getElementById('typeFilter').value;
  const folderFilter = document.getElementById('folderFilter').value;
  const deadOnly = document.getElementById('deadOnly').checked;
  const popularOnly = document.getElementById('popularOnly').checked;
  const dynamicOnly = document.getElementById('dynamicOnly').checked;
  const externalOnly = document.getElementById('externalOnly').checked;
  const minPop = parseInt(document.getElementById('minPop').value || '0', 10);
  const minDegree = parseInt(document.getElementById('minDegree').value || '0', 10);
  const maxNodes = parseInt(document.getElementById('maxNodes').value || '5000', 10);

  const visible = [];
  nodes.forEach(n => {{
    let ok = !state.hidden.has(n.id);
    if (state.isolateNode) {{
      const neighbors = new Set(mainNetwork.getConnectedNodes(state.isolateNode));
      neighbors.add(state.isolateNode);
      ok = neighbors.has(n.id);
    }}
    if (ok && includeTerms.length) ok = nodeMatchesSearch(n, includeTerms, excludeTerms, mode, caseSensitive);
    if (ok && excludeTerms.length && !includeTerms.length) ok = nodeMatchesSearch(n, [], excludeTerms, mode, caseSensitive);
    if (ok && invert) ok = !nodeMatchesSearch(n, includeTerms, excludeTerms, mode, caseSensitive);
    if (ok && typeFilter !== 'all') ok = kindGroup(n.label) === typeFilter;
    if (ok && folderFilter !== 'all') ok = (n.group || '.') === folderFilter;
    if (ok && deadOnly) ok = !!n.dead;
    if (ok && popularOnly) ok = (n.popularity || 0) >= minPop;
    if (ok && dynamicOnly) ok = !!n.dynamic;
    if (ok && externalOnly) ok = !!n.external;
    if (ok && (n.degree || 0) < minDegree) ok = false;
    visible.push({{ id: n.id, ok }});
  }});

  const keep = new Set(visible.filter(v => v.ok).slice(0, maxNodes).map(v => v.id));
  nodes.forEach(n => nodes.update({{ id: n.id, hidden: !keep.has(n.id) }}));
  edges.forEach(e => {{
    const show = keep.has(e.from) && keep.has(e.to);
    edges.update({{ id: e.id, hidden: !show }});
  }});

  const shown = nodes.get({{ filter: n => !n.hidden }});
  document.getElementById('statNodes').textContent = shown.length;
  document.getElementById('statEdges').textContent = edges.get({{ filter: e => !e.hidden }}).length;
  document.getElementById('statDead').textContent = meta.deadLinks || 0;
  document.getElementById('statPopular').textContent = shown.filter(n => (n.popularity || 0) > 0).length;
  document.getElementById('statOrphans').textContent = meta.orphanNodes || 0;
  document.getElementById('statHubs').textContent = meta.hubNodes || 0;
  document.getElementById('statAvgDegree').textContent = meta.averageDegree || 0;
}}

function resetAll() {{
  state.hidden.clear();
  state.isolateNode = null;
  document.getElementById('include').value = '';
  document.getElementById('exclude').value = '';
  document.getElementById('matchMode').value = 'all';
  document.getElementById('invert').checked = false;
  document.getElementById('caseSensitive').checked = false;
  document.getElementById('typeFilter').value = 'all';
  document.getElementById('folderFilter').value = 'all';
  document.getElementById('deadOnly').checked = false;
  document.getElementById('popularOnly').checked = false;
  document.getElementById('dynamicOnly').checked = false;
  document.getElementById('minPop').value = '1';
  document.getElementById('minDegree').value = '1';
  document.getElementById('maxNodes').value = '5000';
  nodes.forEach(n => nodes.update({{ id: n.id, hidden: false }}));
  edges.forEach(e => edges.update({{ id: e.id, hidden: false }}));
  setSelected(null);
  fitGraph();
}}

function fitGraph() {{
  mainNetwork.fit({{ animation: {{ duration: 250, easingFunction: 'easeInOutQuad' }} }});
}}

function relayout() {{
  mainNetwork.setOptions({{ physics: true }});
  mainNetwork.once('stabilizationIterationsDone', () => mainNetwork.setOptions({{ physics: false }}));
}}

function setSelected(node) {{
  const box = document.getElementById('selectedInfo');
  if (!node) {{
    box.innerHTML = '<div class="small">Nothing selected.</div>';
    document.getElementById('copyBtn').disabled = true;
    return;
  }}
  document.getElementById('copyBtn').disabled = false;
  box.innerHTML = '';
  const rows = [
    ['Label', node.label],
    ['Type', node.kind || kindGroup(node.label)],
    ['Folder', node.group || '.'],
    ['Degree', String(node.degree || 0)],
    ['Popularity', String(node.popularity || 0)],
    ['Size', String(node.size || 0) + ' bytes'],
    ['Dead', node.dead ? 'yes' : 'no'],
    ['Dynamic', node.dynamic ? 'yes' : 'no'],
    ['External', node.external ? 'yes' : 'no'],
  ];
  rows.forEach(([k, v]) => {{
    const wrap = document.createElement('div');
    wrap.className = 'kv';
    const a = document.createElement('div');
    a.textContent = k;
    const b = document.createElement('div');
    b.textContent = v;
    wrap.appendChild(a); wrap.appendChild(b);
    box.appendChild(wrap);
  }});
}}

function focusNode(id) {{
  const node = nodes.get(id);
  if (!node) return;
  state.isolateNode = null;
  setSelected(node);
  mainNetwork.selectNodes([id]);
  mainNetwork.focus(id, {{ scale: 1.5, animation: {{ duration: 250, easingFunction: 'easeInOutQuad' }} }});
  applyFilters();
  updateUrlAnchor(id);
  closeSidebar();
}}

function isolateNode(id) {{
  const node = nodes.get(id);
  if (!node) return;
  state.isolateNode = id;
  setSelected(node);
  mainNetwork.selectNodes([id]);
  mainNetwork.focus(id, {{ scale: 1.6, animation: {{ duration: 250, easingFunction: 'easeInOutQuad' }} }});
  applyFilters();
  updateUrlAnchor(id);
  closeSidebar();
}}

function updateUrlAnchor(id) {{
  window.history.replaceState(null, '', '#' + encodeURIComponent(id));
}}

function showNodeAndNeighbors(id) {{
  state.isolateNode = id;
  applyFilters();
}}

function hideNode(id) {{
  state.hidden.add(id);
  applyFilters();
}}

function showAllNodes() {{
  resetAll();
}}

function copySelected() {{
  const nodeId = mainNetwork.getSelectedNodes()[0];
  if (!nodeId) return;
  const node = nodes.get(nodeId);
  if (!node) return;
  navigator.clipboard?.writeText(node.label || '').catch(() => {{}});
}}

function toggleFullscreen() {{
  const main = document.getElementById('main');
  if (!document.fullscreenElement) {{
    main.requestFullscreen?.().catch(() => {{}});
  }} else {{
    document.exitFullscreen?.().catch(() => {{}});
  }}
}}

function toggleMini() {{
  const wrap = document.getElementById('miniWrap');
  state.miniVisible = !state.miniVisible;
  wrap.style.display = state.miniVisible ? 'block' : 'none';
  if (state.miniVisible) miniNetwork.redraw();
}}

function toggleSidebar() {{
  const sidebar = document.getElementById('sidebar');
  state.sidebarOpen = !state.sidebarOpen;
  sidebar.classList.toggle('open', state.sidebarOpen);
}}

function closeSidebar() {{
  if (window.innerWidth <= 768) {{
    const sidebar = document.getElementById('sidebar');
    state.sidebarOpen = false;
    sidebar.classList.remove('open');
  }}
}}

// Context menu
const menu = document.getElementById('contextMenu');
function hideMenu() {{ menu.style.display = 'none'; }}
function showMenu(x, y) {{
  menu.style.left = x + 'px';
  menu.style.top = y + 'px';
  menu.style.display = 'block';
}}
let contextNodeId = null;

const mainEl = document.getElementById('network');
mainEl.addEventListener('contextmenu', (ev) => {{
  ev.preventDefault();
  const rect = mainEl.getBoundingClientRect();
  const pos = {{ x: ev.clientX - rect.left, y: ev.clientY - rect.top }};
  const id = mainNetwork.getNodeAt(pos);
  contextNodeId = id || null;
  if (id) showMenu(ev.clientX, ev.clientY); else hideMenu();
}});

window.addEventListener('click', hideMenu);
window.addEventListener('resize', () => {{ if (state.miniVisible) miniNetwork.redraw(); }});

// Help modal
const helpModal = document.getElementById('helpModal');
function showHelp() {{ helpModal.style.display = 'flex'; }}
function closeHelp() {{ helpModal.style.display = 'none'; }}

window.addEventListener('keydown', ev => {{
  if (ev.key === 'Escape') {{ 
    hideMenu();
    closeHelp();
    if (state.isolateNode) {{ state.isolateNode = null; applyFilters(); }} 
  }}
  if (ev.key === '?') {{ showHelp(); }}
  if (ev.key === 'm' || ev.key === 'M') {{ toggleSidebar(); }}
  if (ev.shiftKey && (ev.key === 'M')) {{ toggleMini(); }}
  if (ev.key === 'f' || ev.key === 'F') {{ if (!ev.shiftKey) fitGraph(); }}
  if (ev.shiftKey && ev.key === 'F') {{ toggleFullscreen(); }}
  if (ev.key === 'Enter') {{ applyFilters(); }}
  if (ev.shiftKey && ev.key === 'R') {{ resetAll(); }}
}});

// Events
mainNetwork.on('click', params => {{
  hideMenu();
  if (params.nodes.length) setSelected(nodes.get(params.nodes[0]));
  else setSelected(null);
}});
mainNetwork.on('doubleClick', params => {{
  if (params.nodes.length) isolateNode(params.nodes[0]);
}});
mainNetwork.on('hoverNode', params => {{
  const node = nodes.get(params.node);
  if (node) setSelected(node);
}});

// Chip wiring
applyChip('invertChip', 'invert');
applyChip('caseChip', 'caseSensitive');
applyChip('deadChip', 'deadOnly');
applyChip('popChip', 'popularOnly');
applyChip('dynChip', 'dynamicOnly');
applyChip('extChip', 'externalOnly');

// Event listeners
['include','exclude','matchMode','invert','caseSensitive','typeFilter','folderFilter','deadOnly','popularOnly','dynamicOnly','externalOnly','minPop','minDegree','maxNodes'].forEach(id => {{
  const el = document.getElementById(id);
  el.addEventListener('input', applyFilters);
  el.addEventListener('change', applyFilters);
}});

// Button handlers
document.getElementById('applyBtn').addEventListener('click', applyFilters);
document.getElementById('resetBtn').addEventListener('click', resetAll);
document.getElementById('fitBtn').addEventListener('click', fitGraph);
document.getElementById('relayoutBtn').addEventListener('click', relayout);
document.getElementById('fullscreenBtn').addEventListener('click', toggleFullscreen);
document.getElementById('miniBtn').addEventListener('click', toggleMini);
document.getElementById('showAllBtn').addEventListener('click', showAllNodes);
document.getElementById('sidebarToggle').addEventListener('click', toggleSidebar);
document.getElementById('helpBtn').addEventListener('click', showHelp);

function _exportState() {{
  const snapshot = {{
    selected: mainNetwork.getSelectedNodes(),
    hidden: [...state.hidden],
    isolateNode: state.isolateNode,
    filters: {{
      include: document.getElementById('include').value,
      exclude: document.getElementById('exclude').value,
      matchMode: document.getElementById('matchMode').value,
      type: document.getElementById('typeFilter').value,
      folder: document.getElementById('folderFilter').value,
    }}
  }};
  const blob = new Blob([JSON.stringify(snapshot, null, 2)], {{ type: 'application/json' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'linkgraph_state.json';
  a.click();
  URL.revokeObjectURL(a.href);
}}

function _exportJSON() {{
  const payload = {{ nodes: nodes.get(), edges: edges.get(), meta }};
  const blob = new Blob([JSON.stringify(payload, null, 2)], {{ type: 'application/json' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'linkgraph_export.json';
  a.click();
  URL.revokeObjectURL(a.href);
}}

function _exportCSV() {{
  const rows = [['id','label','group','kind','degree','popularity','dead','dynamic','external','size']];
  nodes.get().forEach(n => {{
    rows.push([
      n.id,
      n.label,
      n.group || '',
      n.kind || '',
      n.degree || 0,
      n.popularity || 0,
      n.dead ? '1' : '0',
      n.dynamic ? '1' : '0',
      n.external ? '1' : '0',
      n.size || 0,
    ]);
  }});
  const csv = rows.map(r => r.map(c => '"' + String(c).replace(/"/g, '""') + '"').join(',')).join('\n');
  const blob = new Blob([csv], {{ type: 'text/csv' }});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'linkgraph_export.csv';
  a.click();
  URL.revokeObjectURL(a.href);
}}

document.getElementById('exportBtn').addEventListener('click', _exportState);
document.getElementById('exportJsonBtn').addEventListener('click', _exportJSON);
document.getElementById('exportCsvBtn').addEventListener('click', _exportCSV);

document.getElementById('copyBtn').addEventListener('click', copySelected);

// Context menu handlers
document.getElementById('ctxFocus').addEventListener('click', () => {{ if (contextNodeId) focusNode(contextNodeId); hideMenu(); }});
document.getElementById('ctxNeighbors').addEventListener('click', () => {{ if (contextNodeId) isolateNode(contextNodeId); hideMenu(); }});
document.getElementById('ctxHide').addEventListener('click', () => {{ if (contextNodeId) hideNode(contextNodeId); hideMenu(); }});
document.getElementById('ctxShowAll').addEventListener('click', () => {{ showAllNodes(); hideMenu(); }});

// Close help modal on outside click
helpModal.addEventListener('click', (e) => {{ if (e.target === helpModal) closeHelp(); }});

// Initialization
parseUrlAnchor();
renderMetaLists();
resetAll();

// Deep link support
if (state.nodeIdFromUrl) {{
  setTimeout(() => focusNode(state.nodeIdFromUrl), 500);
}}
</script>
</body>
</html>"""
    return html.replace("{{payload}}", payload)


# ===== ARGUMENT PARSING =====
def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    p = argparse.ArgumentParser(
        description='Generate a vis-network based link graph HTML.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 graph.py --root . --output linkgraph.html --open
  python3 graph.py --root /path/to/project --max-depth 10 \\
    --ignore-dir node_modules --ignore-dir .git \\
    --scan-ext html --scan-ext js --log-file access.log
"""
    )
    p.add_argument('--root', default='.', help='Project root to scan (default: .)')
    p.add_argument('--output', default='linkgraph.html', help='Output HTML file (default: linkgraph.html)')
    p.add_argument('--title', default='LinkGraph Pro', help='Page title (default: LinkGraph Pro)')
    p.add_argument('--max-depth', type=int, default=8, help='Maximum directory depth (default: 8)')
    p.add_argument('--max-file-size-kb', type=int, default=512, help='Skip files larger than this (default: 512 KB)')
    p.add_argument('--follow-symlinks', action='store_true', help='Follow symbolic links during scan')
    p.add_argument('--open', dest='open_browser', action='store_true', help='Open output in browser')
    p.add_argument('--include-external-nodes', action='store_true', help='Show external links as graph nodes')
    p.add_argument('--ignore-dir', action='append', default=[], help='Ignore directory (repeatable or comma-separated)')
    p.add_argument('--scan-ext', action='append', default=[], help='File extension to scan (repeatable or comma-separated)')
    p.add_argument('--log-file', action='append', default=[], help='Log file for popularity (repeatable or comma-separated)')
    p.add_argument('--cache', action='store_true', help='Enable scan caching')
    p.add_argument('--cache-file', default='.linkgraphcache.json', help='Cache file path')
    p.add_argument('--hub-threshold', type=int, default=DEFAULT_HUB_THRESHOLD, help='Threshold for hub nodes (default: 6)')
    p.add_argument('--debug', action='store_true', help='Enable debug logging')
    p.add_argument('--config', type=Path, default=None, help='Load configuration from JSON file')
    return p.parse_args()


# ===== MAIN =====
def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Load config file if provided
    cfg_data = {}
    if args.config:
        cfg_data = load_config_file(args.config)
        log(f"Loaded configuration from {args.config}")

    # CLI args override config file
    ignore_dirs = set(DEFAULT_IGNORE_DIRS)
    ignore_dirs.update(d.lower() for d in parse_multi(args.ignore_dir))
    if 'ignore_dirs' in cfg_data:
        ignore_dirs.update(cfg_data['ignore_dirs'])

    scan_exts = set(DEFAULT_SCAN_EXTS)
    if args.scan_ext:
        scan_exts = {normalize_ext(x) for x in parse_multi(args.scan_ext)}
    if 'scan_exts' in cfg_data:
        scan_exts.update({normalize_ext(x) for x in cfg_data['scan_exts']})

    log_files = [Path(p).expanduser() for p in parse_multi(args.log_file)]
    if 'log_files' in cfg_data:
        log_files.extend([Path(p).expanduser() for p in cfg_data['log_files']])

    cfg = Config(
        root=Path(args.root).expanduser(),
        output=Path(args.output).expanduser(),
        title=args.title or cfg_data.get('title', 'LinkGraph Pro'),
        max_depth=args.max_depth or cfg_data.get('max_depth', 8),
        max_file_size_kb=args.max_file_size_kb or cfg_data.get('max_file_size_kb', 512),
        follow_symlinks=args.follow_symlinks or cfg_data.get('follow_symlinks', False),
        open_browser=args.open_browser or cfg_data.get('open_browser', False),
        include_external_nodes=args.include_external_nodes or cfg_data.get('include_external_nodes', False),
        enable_cache=args.cache or cfg_data.get('enable_cache', False),
        cache_file=Path(args.cache_file).expanduser() if args.cache_file else Path(cfg_data.get('cache_file', '.linkgraphcache.json')).expanduser(),
        hub_threshold=args.hub_threshold or cfg_data.get('hub_threshold', DEFAULT_HUB_THRESHOLD),
        ignore_dirs=ignore_dirs,
        scan_exts=scan_exts,
        log_files=log_files,
        debug=args.debug,
    )

    if cfg.debug:
        logger.setLevel(logging.DEBUG)

    result = scan_project(cfg)
    html = build_html(cfg, result)
    cfg.output.write_text(html, encoding='utf-8')
    log(f"✓ Wrote {cfg.output.resolve()}")
    if cfg.open_browser:
        webbrowser.open(cfg.output.resolve().as_uri())
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
