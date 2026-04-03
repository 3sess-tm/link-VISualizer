# LinkGraph Pro - User Manual

## Overview

**LinkGraph Pro** is a powerful Python tool that scans your project for all internal links, external links, dead links, and dynamic/template links, then visualizes them in an interactive HTML-based network graph. It helps you understand the link structure of your project and identify potential issues.

---

## Table of Contents

1. [Installation](#installation)
2. [Quick Start](#quick-start)
3. [Command-Line Usage](#command-line-usage)
4. [Configuration Files](#configuration-files)
5. [The Web Interface](#the-web-interface)
6. [Keyboard Shortcuts](#keyboard-shortcuts)
7. [Advanced Features](#advanced-features)
8. [Examples](#examples)
9. [Statistics Panel](#statistics-panel)
10. [Troubleshooting](#troubleshooting)
11. [Performance Tips](#performance-tips)
12. [Support](#support)

---

## Installation

### Prerequisites

- **Python 3.8+**
- No external dependencies required (uses only standard library)

### Setup

1. Clone or download the repository:
   ```bash
   git clone https://github.com/3sess-tm/link-VISualizer.git
   cd link-VISualizer
   ```

2. Ensure you have Python 3.8 or later:
   ```bash
   python3 --version
   ```

3. Make the script executable (optional, on Unix-like systems):
   ```bash
   chmod +x graph_improved.py
   ```

---

## Quick Start

### Generate a basic graph for your project:

```bash
python3 graph_improved.py --root . --output linkgraph.html --open
```

This will:
- Scan the current directory (`.`)
- Generate an interactive HTML file (`linkgraph.html`)
- Automatically open it in your default browser

---

## Command-Line Usage

### Basic Syntax

```bash
python3 graph_improved.py [OPTIONS]
```

### Project & Output Options

| Option | Description | Default | Example |
|--------|-------------|---------|---------|
| `--root` | Project root directory to scan | `.` | `--root /path/to/project` |
| `--output` | Output HTML file path | `linkgraph.html` | `--output my-graph.html` |
| `--title` | Title for the web page | `LinkGraph Pro` | `--title "My Project Links"` |
| `--open` | Automatically open in browser after generation | disabled | `--open` |

### Directory & File Scanning

| Option | Description | Default | Example |
|--------|-------------|---------|---------|
| `--max-depth` | Maximum directory depth to scan | `8` | `--max-depth 10` |
| `--max-file-size-kb` | Skip files larger than this size | `512 KB` | `--max-file-size-kb 1024` |
| `--follow-symlinks` | Follow symbolic links during scan | disabled | `--follow-symlinks` |
| `--ignore-dir` | Directories to skip (repeatable) | node_modules, .git, __pycache__, vendor, dist, build, .next, .cache | `--ignore-dir node_modules --ignore-dir .git` |
| `--scan-ext` | File extensions to scan (repeatable) | html, htm, css, js, mjs, ts, tsx, php, phtml, twig, xml, json, md | `--scan-ext html --scan-ext js` |

### Log & Popularity Analysis

| Option | Description | Example |
|--------|-------------|---------|
| `--log-file` | Access log file for popularity metrics (repeatable or comma-separated) | `--log-file access.log --log-file traffic.log` |

### Caching & Performance

| Option | Description | Default | Example |
|--------|-------------|---------|---------|
| `--cache` | Enable scan result caching | disabled | `--cache` |
| `--cache-file` | Custom cache file path | `.linkgraphcache.json` | `--cache-file /tmp/.graph-cache.json` |

### Advanced Options

| Option | Description | Default | Example |
|--------|-------------|---------|---------|
| `--hub-threshold` | Minimum degree for "hub" nodes | `6` | `--hub-threshold 10` |
| `--include-external-nodes` | Show external URLs (http://, etc.) as graph nodes | disabled | `--include-external-nodes` |
| `--config` | Load settings from JSON config file | none | `--config .linkgraphrc` |
| `--debug` | Enable debug logging for troubleshooting | disabled | `--debug` |

---

## Configuration Files

You can store settings in a `.linkgraphrc` JSON file to avoid typing long command lines every time.

### Creating a Config File

Create a `.linkgraphrc` in your project root (or anywhere you want):

```json
{
  "root": "./src",
  "output": "linkgraph.html",
  "title": "My Project Links",
  "max_depth": 10,
  "max_file_size_kb": 512,
  "follow_symlinks": false,
  "include_external_nodes": false,
  "enable_cache": true,
  "cache_file": ".linkgraphcache.json",
  "hub_threshold": 6,
  "ignore_dirs": [
    "node_modules",
    ".git",
    "__pycache__",
    "vendor",
    "dist",
    "build",
    ".next",
    ".cache"
  ],
  "scan_exts": [
    "html",
    "htm",
    "css",
    "js",
    "ts",
    "tsx",
    "php",
    "phtml",
    "twig",
    "md",
    "json",
    "xml"
  ],
  "log_files": [
    "./logs/access.log",
    "./logs/traffic.log"
  ],
  "debug": false
}
```

### Using a Config File

```bash
python3 graph_improved.py --config .linkgraphrc
```

**Note:** Command-line arguments override config file settings.

---

## The Web Interface

### Layout Overview

The generated HTML file has three main sections:

```
┌─────────────────────────────────────────────────────┐
│                    Toolbar (pills)                  │
├────────────��─┬──────────────────────────────────────┤
│              │                                      │
│   SIDEBAR    │          NETWORK GRAPH               │
│              │           (Interactive)              │
│  - Search    │                                      │
│  - Filters   │                       ┌────────────┐ │
│  - Stats     │                       │  Minimap   │ │
│  - Actions   │                       └────────────┘ │
│              │                                      │
└──────────────┴──────────────────────────────────────┘
```

### Sidebar Sections

#### **Search**
- **Include terms:** Words that must appear in node labels
- **Exclude terms:** Words to filter out
- **Match mode:** 
  - "Match all" — All include terms must be present
  - "Match any" — Any include term is sufficient
  - "Show non-matches" — Reverse the logic
- **Invert checkbox:** Flip matching logic
- **Case sensitive checkbox:** Case-sensitive matching
- **Apply/Reset/Fit buttons:** Execute searches and reset filters

#### **Filters**
- **Type filter:** Show only specific file types (HTML, CSS, JS, etc.)
- **Folder filter:** Show only files in specific folders
- **Dead only:** Show only broken/missing links
- **Popular only:** Show only links from access logs
- **Dynamic only:** Show only template/dynamic links
- **External only:** Show only external URLs
- **Min popularity:** Only show nodes with X+ log hits
- **Min degree:** Only show nodes with X+ connections
- **Max nodes:** Limit visible nodes (helpful for large graphs)
- **Sort order:** Arrange by importance, popularity, alphabetical, folder, or type

#### **Actions**
- **Fullscreen:** Toggle fullscreen view
- **Minimap:** Toggle minimap visibility (bottom-right)
- **Layout:** Re-run physics simulation for better positioning
- **Show all:** Reset all filters
- **Export state:** Save current view state to JSON
- **Export JSON:** Export full graph data
- **Export CSV:** Export node data as spreadsheet
- **Copy selected:** Copy selected node path to clipboard
- **? Keyboard Shortcuts:** Open help modal

#### **Legend**
Color key for different node types:
- 🔴 HTML / page files
- 🔵 CSS stylesheets
- 🟡 JavaScript / TypeScript
- 🔴 Dead links (bright red)
- 🟠 Dynamic links
- 🔵 External links (cyan)
- 🟢 Popular nodes (from logs)

#### **Stats**
Real-time statistics on the visible graph:
- Nodes, Edges, Dead links
- Popular nodes, Orphans, Hub nodes
- Average degree

#### **Top Nodes & Top Folders**
Lists of the most important nodes and folders (clickable).

#### **Selected**
Details about the currently selected node.

### Navigation & Interaction

| Action | How |
|--------|-----|
| **Pan** | Click and drag the graph |
| **Zoom in/out** | Scroll up/down |
| **Select a node** | Click on it |
| **Focus on node** | Double-click it |
| **Context menu** | Right-click a node |
| **Multi-select** | Ctrl+Click (or Cmd+Click on Mac) |

### Context Menu (Right-Click)

Right-click any node to see:

- **Focus node** — Center and zoom to that node
- **Show node + neighbors** — Isolate this node and all connected nodes
- **Hide node** — Remove node from view temporarily
- **Show all** — Restore all hidden nodes

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| `Escape` | Close modals, clear isolation |
| `M` | Toggle sidebar (mobile view) |
| `Shift + M` | Toggle minimap |
| `F` | Fit entire graph into view |
| `Shift + F` | Toggle fullscreen mode |
| `Enter` | Apply current filters |
| `Shift + R` | Reset all filters |
| `?` | Show keyboard shortcuts help |

---

## Advanced Features

### Search & Filtering

#### Search Terms

The **Include** and **Exclude** fields support:
- Simple terms: `index`
- Quoted phrases: `"main content"`
- Multiple terms: `header footer navigation`
- Comma-separated: `term1, term2, term3`

**Examples:**
- `include: "nav"` — Shows only nodes with "nav" in the label
- `include: "index" exclude: "404"` — Shows index pages but not 404
- `exclude: ".min.js"` — Hides minified JavaScript files

#### Match Modes

- **Match all** — All include terms must be present (AND logic)
- **Match any** — At least one include term must be present (OR logic)
- **Show non-matches** — Show everything EXCEPT matches

#### Special Filters

- **Dead only** — Show only targets that don't exist
- **Popular only** — Show only nodes that appear in access logs
- **Dynamic only** — Show only template links with `${...}` or `{{...}}`
- **External only** — Show only external URLs (http://, https://, mailto:, etc.)

#### Node Limits

- **Min popularity:** Slider to show only nodes with X log hits minimum
- **Min degree:** Slider to show only nodes with X+ connections
- **Max nodes:** Cap the visible nodes (useful for huge graphs)

### Popularity Metrics

If you provide access logs (`--log-file`), LinkGraph tracks which pages are requested:

```bash
python3 graph_improved.py --root . --log-file apache_access.log --open
```

Nodes will have a **popularity** score based on log hits. Use the **Popular only** filter to find your most-accessed pages.

### Deep Linking

The URL automatically updates as you navigate. You can share links to specific nodes:

**Original HTML:**
```
linkgraph.html
```

**After clicking a node:**
```
linkgraph.html#src%2Findex.html
```

Share this link with others to jump directly to that node!

### Export Options

#### **Export state** (JSON)
Saves your current filters and view:
```json
{
  "selected": ["node123"],
  "hidden": ["orphan1", "orphan2"],
  "isolateNode": null,
  "filters": {
    "include": "nav",
    "exclude": "",
    "matchMode": "all",
    "type": "html",
    "folder": "src"
  }
}
```

#### **Export JSON** (Full graph)
Complete graph data:
```json
{
  "nodes": [...],
  "edges": [...],
  "meta": {
    "fileCount": 523,
    "nodeCount": 1204,
    "edgeCount": 3891,
    ...
  }
}
```

#### **Export CSV** (Spreadsheet)
Node data as CSV for analysis in Excel/Sheets:
```csv
id,label,group,kind,degree,popularity,dead,dynamic,external,size
node1,src/index.html,src,html,12,45,0,0,0,2048
node2,src/css/style.css,src/css,css,8,120,0,0,0,4096
...
```

---

## Node Types & Colors

### File Types

| Type | Color | Extensions |
|------|-------|------------|
| HTML / Pages | 🔴 #e34c26 (Red-Orange) | .html, .htm, .twig, .php, .phtml |
| CSS | 🔵 #2965f1 (Blue) | .css, .scss, .sass, .less |
| JavaScript / TypeScript | 🟡 #f7df1e (Yellow) | .js, .mjs, .ts, .tsx |
| JSON | 🟢 #2ea043 (Green) | .json |
| Markdown | ⚫ #8b949e (Gray) | .md, .markdown |
| XML | ⚪ #c9d1d9 (Light Gray) | .xml |
| Other | 🔵 #58a6ff (Cyan) | other extensions |

### Link States

| State | Color | Meaning |
|-------|-------|---------|
| Dead Link | 🔴 #f85149 (Bright Red) | Target file doesn't exist |
| Dynamic Link | 🟠 #d29922 (Orange) | Contains template placeholders (`${var}`, `{{var}}`) |
| External Link | 🔵 #58a6ff (Cyan) | Links to http://, https://, mailto:, etc. |
| Popular | 🟢 (Green tint) | Appears in provided access logs |

### Node Size

Node size is calculated from:
- **Degree:** Number of incoming/outgoing connections
- **Popularity:** Hits from access logs (if provided)
- **File size:** Physical file size in bytes

Larger nodes = more important/connected pages.

---

## Examples

### Example 1: Basic project scan

```bash
python3 graph_improved.py \
  --root . \
  --output linkgraph.html \
  --open
```

### Example 2: Web project with specific file types

```bash
python3 graph_improved.py \
  --root ./website \
  --output website-links.html \
  --ignore-dir node_modules \
  --ignore-dir .git \
  --scan-ext html \
  --scan-ext css \
  --scan-ext js \
  --open
```

### Example 3: Include log file for popularity metrics

```bash
python3 graph_improved.py \
  --root . \
  --output linkgraph.html \
  --log-file /var/log/apache2/access.log \
  --open
```

This will color-code and size nodes based on which pages are actually being visited.

### Example 4: Show external links as nodes

```bash
python3 graph_improved.py \
  --root . \
  --output linkgraph.html \
  --include-external-nodes \
  --open
```

Now external links appear as nodes, helping you visualize outbound dependencies.

### Example 5: Deep project scan with caching

```bash
python3 graph_improved.py \
  --root /large/project \
  --max-depth 12 \
  --cache \
  --open
```

First run takes longer, but subsequent runs are instant!

### Example 6: Find dead links

```bash
python3 graph_improved.py \
  --root . \
  --output linkgraph.html
```

Then:
1. Open `linkgraph.html`
2. In sidebar, click the "Dead only" checkbox
3. Review all broken links at a glance

### Example 7: Using a config file

Create `.linkgraphrc`:
```json
{
  "root": "./src",
  "output": "graph.html",
  "max_depth": 10,
  "scan_exts": ["html", "css", "js"],
  "ignore_dirs": ["node_modules", ".git"]
}
```

Then run:
```bash
python3 graph_improved.py --config .linkgraphrc --open
```

### Example 8: Multiple log files

```bash
python3 graph_improved.py \
  --root . \
  --output linkgraph.html \
  --log-file access.log \
  --log-file error.log \
  --open
```

---

## Statistics Panel

The **Stats** section shows real-time metrics on the visible graph:

| Metric | Meaning |
|--------|---------|
| **Nodes** | Count of visible nodes |
| **Edges** | Count of visible links |
| **Dead links** | Number of broken links in entire project |
| **Popular nodes** | Nodes with at least 1 log hit |
| **Orphans** | Nodes with degree 0 (no connections) |
| **Hubs** | Nodes with degree ≥ threshold (default: 6) |
| **Avg degree** | Average connections per node |

**Note:** These update as you apply filters.

---

## Troubleshooting

### Q: The graph is very slow or won't load

**A:** Try these steps in order:

1. **Reduce depth:** `--max-depth 5`
2. **Cap nodes:** In UI, lower "Max nodes" slider
3. **Enable cache:** `--cache` (faster on re-runs)
4. **Use filters:** Hide orphans or low-degree nodes in the UI
5. **Exclude large dirs:** `--ignore-dir node_modules --ignore-dir .git`

### Q: No links are being detected

**A:** Check the following:

1. **File extensions:** Verify you're scanning the right types
   ```bash
   python3 graph_improved.py --root . --scan-ext html --scan-ext js --debug
   ```

2. **Root directory:** Ensure it's correct
   ```bash
   python3 graph_improved.py --root /path/to/project --debug
   ```

3. **Debug mode:** Enable to see what's happening
   ```bash
   python3 graph_improved.py --debug
   ```

### Q: External links aren't showing

**A:** 
1. Enable external nodes: `--include-external-nodes`
2. In UI, make sure the "External only" filter is unchecked (unless you specifically want only external links)

### Q: "Dead links" are showing but the files exist

**A:** This might be because:

1. **Symlinks:** Use `--follow-symlinks` if you have symbolic links
   ```bash
   python3 graph_improved.py --follow-symlinks --open
   ```

2. **Relative path issues:** The link might not resolve correctly from the source file
3. **Dynamic links:** Links with placeholders are marked as "dynamic" (not dead)

### Q: How do I find the most important pages?

**A:**
1. Open the HTML file
2. Look at **"Top nodes"** in the sidebar
3. Click any node to see details
4. Sort by **"Importance"** (already default)
5. Double-click a node to focus on it and see its connections

### Q: Can I use this on Windows?

**A:** Yes! Works perfectly on Windows 10/11:

```powershell
python graph_improved.py --root . --output linkgraph.html --open
```

Use the same commands as Linux/Mac.

### Q: Can I automate this to run daily?

**A:** Yes! Create a script:

**Linux/Mac (`scan.sh`):**
```bash
#!/bin/bash
python3 graph_improved.py \
  --config .linkgraphrc \
  --output reports/linkgraph-$(date +%Y-%m-%d).html
```

**Windows (`scan.bat`):**
```batch
@echo off
for /f "tokens=2-4 delims=/ " %%a in ('date /t') do (set mydate=%%c-%%a-%%b)
python graph_improved.py --config .linkgraphrc --output reports\linkgraph-%mydate%.html
```

Then schedule with:
- **Linux/Mac:** `crontab -e` → add `0 2 * * * /path/to/scan.sh`
- **Windows:** Task Scheduler

### Q: The output HTML is huge, how do I view it?

**A:**
- **Modern browser:** Most modern browsers handle large graphs well
- **Simplify:** Use filters to hide low-degree nodes before sharing
- **Export CSV:** For analysis in Excel/Sheets
- **Split project:** Scan sections separately

### Q: How do I interpret the graph layout?

**A:**
- **Central nodes:** Highly connected pages (likely important)
- **Isolated clusters:** Separate sections of your project
- **Long chains:** Deeply nested structures
- **Hubs:** Pages linked from many places (navigation, home page, etc.)

---

## Performance Tips

### Optimization Strategies

1. **Use caching**
   ```bash
   python3 graph_improved.py --cache --open
   ```
   First run: 30s. Subsequent runs: <1s.

2. **Reduce scanning depth**
   ```bash
   python3 graph_improved.py --max-depth 5
   ```
   Default is 8. Deeper scans take longer.

3. **Exclude large directories**
   ```bash
   python3 graph_improved.py \
     --ignore-dir node_modules \
     --ignore-dir .git \
     --ignore-dir vendor
   ```
   These directories often contain thousands of files.

4. **Filter in the UI, don't re-scan**
   - Use the "Max nodes" slider instead of re-running
   - Apply filters to hide low-degree nodes

5. **Split large projects**
   ```bash
   # Scan frontend only
   python3 graph_improved.py --root ./frontend --output frontend.html
   
   # Scan backend only
   python3 graph_improved.py --root ./backend --output backend.html
   ```

6. **Increase file size limit for faster scanning**
   ```bash
   python3 graph_improved.py --max-file-size-kb 2048
   ```
   If your project doesn't have massive files, this helps skip large binaries.

### Typical Performance

- **Small project (< 100 files):** < 1 second
- **Medium project (100-1000 files):** 1-10 seconds
- **Large project (1000-10000 files):** 10-60 seconds
- **Very large project (10000+ files):** 1-5 minutes (with caching: < 1 second after)

---

## Supported Link Types

### Detected in HTML

```html
<a href="/path/to/page">Link</a>
<link rel="stylesheet" href="style.css">
<script src="script.js"></script>
<img src="image.png">
<form action="/submit">
```

### Detected in CSS

```css
@import url("other.css");
background: url("image.png");
```

### Detected in JavaScript

```js
import Component from './component.js';
const data = require('./data.json');
from './module.js' import something;
```

### Detected in JSON

```json
{ "url": "./path/to/file" }
```

### Detected in Markdown

```markdown
[Link](./page.html)
![Image](./img.png)
```

---

## Support & Contributing

For issues, questions, or contributions:

- **GitHub Repository:** https://github.com/3sess-tm/link-VISualizer
- **Report a bug:** Create an issue on GitHub
- **Suggest a feature:** Open a discussion or issue

---

## License

Please refer to the LICENSE file in the repository.

---

**Happy graphing! 🔗**

```

This is the complete, comprehensive user manual. You can save this as `MANUAL.md` or `USER_GUIDE.md` in your repository!
