# INRA - Universal Linux System Cleaner & Package Purger

INRA is a smart, safe, low-level system utility designed to analyze installed packages across different Linux distributions, identify candidates for cleaning, estimate reclaimable space, and safely purge unused packages.

INRA currently supports **Arch Linux** (Pacman), **Debian/Ubuntu** (APT/DPKG), **Fedora/RHEL** (RPM/DNF), **Void Linux** (XBPS), **Alpine Linux** (APK), **Gentoo Linux** (Portage), and **NixOS** (Nix) with zero external python library dependencies.



## Key Features

1. **Distro-Wide Support**: Automatically detects package manager (Pacman, APT, RPM/DNF, XBPS, APK, Portage, Nix) and adapts its queries and commands.
2. **Interactive TUI**:
   - Keyboard-driven navigation (arrow keys, spacebar, etc.).
   - Live category search (press `/` key to filter list).
   - Multi-column sort options (by individual size, recursive size, package name, install date).
   - Package inspector showing license, URL, and sub-dependencies.

4. **True Dependency Resolution**: Detects strict and optional orphans (dependencies installed automatically but no longer required by any package).
5. **Smart Heuristic Classification**: Organizes explicit packages into logical tabs:
   - **GUI Applications** (detects `.desktop` files owned by packages)
   - **Dev / Build Tools** (headers, compilers, debuggers, libraries)
   - **Fonts & Themes** (icons, cursor themes, font packages)
   - **CLI & Others** (daemons, command-line utilities, other packages)
6. **System Cleanup Utilities**:
   - Clean package manager download cache (Arch, Debian, Fedora options).
   - Vacuum systemd journal logs by age or size.
7. **Scriptable Commands**: Non-interactive reports with `--dry-run`, `--min-size`, and `--json`.

---

## Getting Started

### 1. Requirements
- Python 3.6+
- standard Linux command utilities

### 2. How to Run

#### Interactive TUI Mode
Launch the TUI interface in your terminal:
```bash
./inra
```

- Use **Up/Down Arrows** to select a package.
- Press **Spacebar** to toggle selection for cleaning.
- Press **/** to enter search query.
- Press **S** to cycle through sort configurations.
- Press **I** to inspect details (dependencies, description, installation date).
- Press **B** to go back.
- Press **R** to review and run the cleanup.



#### Non-Interactive Dry Run
Print recommendations directly to stdout:
```bash
./inra --dry-run
```

Filter candidate packages by minimum recursive size (e.g. 20M, 100MB):
```bash
./inra --dry-run --min-size 50M
```

#### JSON Output (ideal for pipelines)
Export the categorization and package data as JSON:
```bash
./inra --json
```

---

## Configuration

You can configure packages to be excluded from cleanup recommendations by listing them (one per line) in:
`~/.config/inra/ignore.conf`

*Example configuration:*
```conf
# INRA Ignore List
# Put package names here (one per line) to exclude them from cleanup recommendations.
neovim
rsync
```

---

## Packaging

The repository contains an automated build script `build_packages.sh` to package INRA for different systems. It generates:
- `.deb` package (Debian/Ubuntu/Mint)
- `.rpm` package (Fedora/RHEL/CentOS)
- `.appimage` package (Universal standalone binary)
- `.tar.gz` archive (Source code & assets)

To generate local packages, install `dpkg-dev`, `rpm`, and `alien`, then run:
```bash
./build_packages.sh <version>
```

Packages are automatically generated and published to GitHub Releases upon pushing tags matching `v*`.

---

## License

This project is licensed under the **GNU General Public License v3 (GPLv3)**. See [LICENSE](LICENSE) for details.
