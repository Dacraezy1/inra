#!/usr/bin/env python3
import sys
import os
import re
import time
import json
import subprocess
import argparse
import shutil
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import webbrowser
import platform

# ANSI Colors
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"

NO_COLOR = False

def color_text(text, color_code):
    if NO_COLOR:
        return text
    return f"{color_code}{text}{RESET}"

# Custom exception for package manager issues
class PackageManagerError(Exception):
    pass

# Package representation
class Package:
    def __init__(self, name, version, desc, isize, reason, url="", licenses=None, groups=None, depends=None, optdepends=None, files=None, installdate=0, provides=None):
        self.name = name
        self.version = version
        self.desc = desc
        self.isize = isize  # in bytes
        self.reason = reason  # 0 = explicit (manual), 1 = dependency (auto)
        self.url = url
        self.licenses = licenses or []
        self.groups = groups or []
        self.depends = depends or []
        self.optdepends = optdepends or []
        self.files = files or []
        self.installdate = installdate
        self.provides = provides or []

# =====================================================================
# BACKENDS FOR PACKAGE MANAGERS
# =====================================================================

class PacmanBackend:
    """Arch Linux Pacman Backend - Parses database files directly for extreme speed."""
    def __init__(self):
        self.db_path = "/var/lib/pacman/local"
        if not os.path.exists(self.db_path):
            raise PackageManagerError("Pacman database not found at /var/lib/pacman/local")

    def get_installed_packages(self):
        packages = []
        try:
            entries = os.listdir(self.db_path)
        except Exception as e:
            raise PackageManagerError(f"Failed to read pacman DB directory: {e}")

        for entry in entries:
            if entry == "ALPM_DB_VERSION" or not os.path.isdir(os.path.join(self.db_path, entry)):
                continue
            
            desc_path = os.path.join(self.db_path, entry, "desc")
            files_path = os.path.join(self.db_path, entry, "files")
            if not os.path.exists(desc_path):
                continue

            pkg_data = self._parse_desc(desc_path)
            if not pkg_data.get("name"):
                continue

            # Detect if GUI or font using files list efficiently
            has_gui = False
            is_font = False
            if os.path.exists(files_path):
                try:
                    with open(files_path, 'r', errors='ignore') as f:
                        for line in f:
                            line_strip = line.strip()
                            if "usr/share/applications/" in line_strip and line_strip.endswith(".desktop"):
                                has_gui = True
                            if "usr/share/fonts/" in line_strip:
                                is_font = True
                            if has_gui and is_font:
                                break
                except Exception:
                    pass

            # Fallback font name matching
            name_lower = pkg_data["name"].lower()
            if not is_font and (name_lower.startswith("ttf-") or name_lower.startswith("otf-") or name_lower.startswith("font-") or "font" in name_lower):
                is_font = True

            # Populate Package
            p = Package(
                name=pkg_data["name"],
                version=pkg_data.get("version", ""),
                desc=pkg_data.get("desc", ""),
                isize=int(pkg_data.get("size", 0)),
                reason=int(pkg_data.get("reason", 0)),
                url=pkg_data.get("url", ""),
                licenses=pkg_data.get("licenses", []),
                groups=pkg_data.get("groups", []),
                depends=pkg_data.get("depends", []),
                optdepends=pkg_data.get("optdepends", []),
                provides=pkg_data.get("provides", []),
                installdate=int(pkg_data.get("installdate", 0))
            )
            # Tag files info
            p.has_gui = has_gui
            p.is_font = is_font
            packages.append(p)

        return packages

    def _parse_desc(self, path):
        data = {}
        current_field = None
        current_list = []
        try:
            with open(path, 'r', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('%') and line.endswith('%'):
                        if current_field:
                            data[current_field] = current_list if len(current_list) > 1 or current_field in ["licenses", "groups", "depends", "optdepends", "provides"] else (current_list[0] if current_list else "")
                        current_field = line[1:-1].lower()
                        current_list = []
                    elif line:
                        current_list.append(line)
                if current_field:
                    data[current_field] = current_list if len(current_list) > 1 or current_field in ["licenses", "groups", "depends", "optdepends", "provides"] else (current_list[0] if current_list else "")
        except Exception:
            pass
        return data

    def clean_cache(self, mode):
        cmds = {
            "1": ["sudo", "paccache", "-r"],
            "2": ["sudo", "paccache", "-rk1"],
            "3": ["sudo", "paccache", "-rvu"],
            "4": ["sudo", "pacman", "-Scc", "--noconfirm"]
        }
        return cmds.get(str(mode))

    def get_cache_size(self):
        try:
            res = subprocess.run(["du", "-sh", "/var/cache/pacman/pkg"], capture_output=True, text=True)
            if res.returncode == 0:
                return res.stdout.split()[0]
        except Exception:
            pass
        return "Unknown"

    def get_uninstall_cmd(self, packages):
        return ["pacman", "-Rns"] + packages


class AptBackend:
    """Debian/Ubuntu APT Backend - Parses status and extended_states for high accuracy."""
    def __init__(self):
        self.status_path = "/var/lib/dpkg/status"
        self.extended_states_path = "/var/lib/apt/extended_states"
        if not os.path.exists(self.status_path):
            raise PackageManagerError("DPKG status file not found at /var/lib/dpkg/status")

    def get_installed_packages(self):
        # 1. Parse extended states to find Auto-Installed packages
        auto_installed = set()
        if os.path.exists(self.extended_states_path):
            try:
                with open(self.extended_states_path, 'r', errors='ignore') as f:
                    content = f.read()
                    blocks = content.split("\n\n")
                    for block in blocks:
                        pkg_name = None
                        is_auto = False
                        for line in block.splitlines():
                            if line.startswith("Package:"):
                                pkg_name = line.split(":", 1)[1].strip()
                            elif line.startswith("Auto-Installed:"):
                                val = line.split(":", 1)[1].strip()
                                if val == "1":
                                    is_auto = True
                        if pkg_name and is_auto:
                            auto_installed.add(pkg_name)
            except Exception:
                pass

        # 2. Parse DPKG status file
        packages = []
        try:
            with open(self.status_path, 'r', errors='ignore') as f:
                content = f.read()
                blocks = content.split("\n\n")
        except Exception as e:
            raise PackageManagerError(f"Failed to read dpkg status file: {e}")

        for block in blocks:
            if not block.strip():
                continue
            
            pkg_data = {}
            current_field = None
            desc_lines = []
            
            for line in block.splitlines():
                if line.startswith(" ") or line.startswith("\t"):
                    if current_field == "description":
                        desc_lines.append(line.strip())
                else:
                    if ":" in line:
                        key, val = line.split(":", 1)
                        current_field = key.strip().lower()
                        pkg_data[current_field] = val.strip()
            
            if pkg_data.get("status") != "install ok installed":
                continue

            name = pkg_data.get("package")
            if not name:
                continue

            # Format description
            desc = pkg_data.get("description", "")
            if desc_lines:
                desc = desc + " " + " ".join(desc_lines)
            
            desc = re.sub(r'\s+', ' ', desc).strip()

            size_kb = int(pkg_data.get("installed-size", 0))
            isize = size_kb * 1024

            reason = 1 if name in auto_installed else 0

            # Depends / Pre-Depends
            depends = []
            for dep_field in ["depends", "pre-depends"]:
                if dep_field in pkg_data:
                    parts = pkg_data[dep_field].split(",")
                    for part in parts:
                        part = part.strip()
                        alt = part.split("|")[0].strip()
                        clean_name = re.sub(r'\(.*\)', '', alt).strip()
                        if clean_name:
                            depends.append(clean_name)

            # Recommends / Suggests
            optdepends = []
            for opt_field in ["recommends", "suggests"]:
                if opt_field in pkg_data:
                    parts = pkg_data[opt_field].split(",")
                    for part in parts:
                        part = part.strip()
                        alt = part.split("|")[0].strip()
                        clean_name = re.sub(r'\(.*\)', '', alt).strip()
                        if clean_name:
                            optdepends.append(clean_name)

            # Check if GUI or Font
            has_gui = False
            is_font = False
            
            info_list_path = f"/var/lib/dpkg/info/{name}.list"
            if not os.path.exists(info_list_path):
                dpkg_info_dir = "/var/lib/dpkg/info"
                if os.path.exists(dpkg_info_dir):
                    try:
                        for fn in os.listdir(dpkg_info_dir):
                            if fn.startswith(name + ":") and fn.endswith(".list"):
                                info_list_path = os.path.join(dpkg_info_dir, fn)
                                break
                    except Exception:
                        pass
            
            if os.path.exists(info_list_path):
                try:
                    with open(info_list_path, 'r', errors='ignore') as lf:
                        for line in lf:
                            line_strip = line.strip()
                            if "usr/share/applications/" in line_strip and line_strip.endswith(".desktop"):
                                has_gui = True
                            if "usr/share/fonts/" in line_strip:
                                is_font = True
                            if has_gui and is_font:
                                break
                except Exception:
                    pass

            name_lower = name.lower()
            if not is_font and (name_lower.startswith("fonts-") or name_lower.endswith("-fonts") or "font" in name_lower):
                is_font = True

            url = pkg_data.get("homepage", "")

            provides = []
            if "provides" in pkg_data:
                provides = [p.strip() for p in pkg_data["provides"].split(",")]

            p = Package(
                name=name,
                version=pkg_data.get("version", ""),
                desc=desc,
                isize=isize,
                reason=reason,
                url=url,
                depends=depends,
                optdepends=optdepends,
                provides=provides,
                installdate=0
            )
            p.has_gui = has_gui
            p.is_font = is_font
            packages.append(p)

        return packages

    def clean_cache(self, mode):
        if str(mode) == "4":
            return ["sudo", "apt-get", "clean"]
        return ["sudo", "apt-get", "autoclean"]

    def get_cache_size(self):
        try:
            res = subprocess.run(["du", "-sh", "/var/cache/apt/archives"], capture_output=True, text=True)
            if res.returncode == 0:
                return res.stdout.split()[0]
        except Exception:
            pass
        return "Unknown"

    def get_uninstall_cmd(self, packages):
        return ["apt-get", "purge", "--auto-remove"] + packages


class RpmBackend:
    """Fedora/RHEL/CentOS RPM Backend - Uses rpm CLI and DNF query tool."""
    def __init__(self):
        if not shutil.which("rpm"):
            raise PackageManagerError("RPM command not found in PATH")

    def get_installed_packages(self):
        reasons = {}
        if shutil.which("dnf"):
            try:
                res = subprocess.run(["dnf", "repoquery", "--installed", "--qf", "%{name}\\t%{reason}"], capture_output=True, text=True)
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        parts = line.strip().split("\t")
                        if len(parts) == 2:
                            reasons[parts[0]] = 1 if parts[1] == "dependency" else 0
            except Exception:
                pass

        qf = "PKG:%{NAME}\\nVER:%{VERSION}\\nSIZ:%{SIZE}\\nURL:%{URL}\\nSUM:%{SUMMARY}\\nDEP:[%{REQUIRENAME}, ]\\nPROV:[%{PROVIDENAME}, ]\\nINSTALL:%{INSTALLTIME}\\n\\n"
        try:
            res = subprocess.run(["rpm", "-qa", "--queryformat", qf], capture_output=True, text=True, errors='ignore')
            if res.returncode != 0:
                raise PackageManagerError(f"RPM command failed: {res.stderr}")
            content = res.stdout
        except Exception as e:
            raise PackageManagerError(f"Failed to query rpm: {e}")

        gui_packages = set()
        if os.path.exists("/usr/share/applications"):
            try:
                desktops = [os.path.join("/usr/share/applications", f) for f in os.listdir("/usr/share/applications") if f.endswith(".desktop")]
                if desktops:
                    batch_cmd = ["rpm", "-qf", "--queryformat", "%{NAME}\\n"] + desktops[:200]
                    res_gui = subprocess.run(batch_cmd, capture_output=True, text=True, errors='ignore')
                    if res_gui.returncode == 0:
                        for line in res_gui.stdout.splitlines():
                            if line.strip() and "not owned" not in line:
                                gui_packages.add(line.strip())
            except Exception:
                pass

        packages = []
        blocks = content.split("\n\n")
        for block in blocks:
            if not block.strip():
                continue
            
            pkg_data = {}
            for line in block.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    pkg_data[key.strip()] = val.strip()

            name = pkg_data.get("PKG")
            if not name:
                continue

            reason = reasons.get(name, 0)

            depends = []
            dep_str = pkg_data.get("DEP", "[]")
            if dep_str.startswith("[") and dep_str.endswith("]"):
                dep_str = dep_str[1:-1]
                if dep_str:
                    depends = [d.strip() for d in dep_str.split(",") if d.strip() and not d.strip().startswith("rpmlib")]

            provides = []
            prov_str = pkg_data.get("PROV", "[]")
            if prov_str.startswith("[") and prov_str.endswith("]"):
                prov_str = prov_str[1:-1]
                if prov_str:
                    provides = [p.strip() for p in prov_str.split(",") if p.strip()]

            size = int(pkg_data.get("SIZ", 0))

            has_gui = name in gui_packages
            name_lower = name.lower()
            is_font = name_lower.startswith("google-") or name_lower.startswith("fonts-") or "font" in name_lower

            p = Package(
                name=name,
                version=pkg_data.get("VER", ""),
                desc=pkg_data.get("SUM", ""),
                isize=size,
                reason=reason,
                url=pkg_data.get("URL", ""),
                depends=depends,
                provides=provides,
                installdate=int(pkg_data.get("INSTALL", 0))
            )
            p.has_gui = has_gui
            p.is_font = is_font
            packages.append(p)

        return packages

    def clean_cache(self, mode):
        return ["sudo", "dnf", "clean", "all"]

    def get_cache_size(self):
        try:
            res = subprocess.run(["du", "-sh", "/var/cache/dnf"], capture_output=True, text=True)
            if res.returncode == 0:
                return res.stdout.split()[0]
        except Exception:
            pass
        return "Unknown"

    def get_uninstall_cmd(self, packages):
        return ["dnf", "remove"] + packages


class XbpsBackend:
    """Void Linux XBPS Backend - Parses XML package plist directly or runs xbps CLI queries."""
    def __init__(self):
        self.db_path = "/var/db/xbps/pkgdb-0.3.plist"
        if not os.path.exists(self.db_path) and not shutil.which("xbps-query"):
            raise PackageManagerError("XBPS package database or commands not found")

    def get_installed_packages(self):
        packages = []
        
        # 1. Parse plist directly (Fast pure-python path)
        if os.path.exists(self.db_path):
            import plistlib
            try:
                with open(self.db_path, 'rb') as f:
                    db_data = plistlib.load(f)
                
                if isinstance(db_data, dict):
                    entries = []
                    if "_meta" in db_data or "pkgname" in next(iter(db_data.values()), {}):
                        entries = db_data.values()
                    elif "packages" in db_data:
                        entries = db_data["packages"].values()
                    else:
                        entries = db_data.values()

                    for pkg_info in entries:
                        if not isinstance(pkg_info, dict):
                            continue
                        name = pkg_info.get("pkgname")
                        if not name:
                            continue
                        
                        version = pkg_info.get("version", "")
                        desc = pkg_info.get("short_desc", "")
                        size = int(pkg_info.get("installed_size", 0))
                        
                        is_auto = pkg_info.get("automatic-install", False)
                        reason = 1 if is_auto else 0
                        
                        depends = []
                        dep_list = pkg_info.get("run_depends", [])
                        for dep in dep_list:
                            clean_name = re.split(r'[<>=]', dep)[0].strip()
                            if clean_name:
                                depends.append(clean_name)
                                
                        provides = []
                        prov_list = pkg_info.get("provides", [])
                        for prov in prov_list:
                            clean_name = re.split(r'[<>=]', prov)[0].strip()
                            if clean_name:
                                provides.append(clean_name)
                                
                        url = pkg_info.get("homepage", "")
                        license_str = pkg_info.get("license", "")
                        licenses = [l.strip() for l in license_str.split(",") if l.strip()]
                        
                        name_lower = name.lower()
                        is_font = name_lower.startswith("font-") or "font" in name_lower
                        
                        has_gui = False
                        files_list = pkg_info.get("files", [])
                        for fn in files_list:
                            if "usr/share/applications/" in fn and fn.endswith(".desktop"):
                                has_gui = True
                                break
                        
                        p = Package(
                            name=name,
                            version=version,
                            desc=desc,
                            isize=size,
                            reason=reason,
                            url=url,
                            licenses=licenses,
                            depends=depends,
                            provides=provides,
                            installdate=0
                        )
                        p.has_gui = has_gui
                        p.is_font = is_font
                        packages.append(p)
                    
                    return packages
            except Exception:
                pass

        # 2. Fallback to CLI
        try:
            res = subprocess.run(["xbps-query", "-l"], capture_output=True, text=True, errors='ignore')
            if res.returncode == 0:
                auto_installs = set()
                res_auto = subprocess.run(["xbps-query", "-O"], capture_output=True, text=True, errors='ignore')
                if res_auto.returncode == 0:
                    for line in res_auto.stdout.splitlines():
                        auto_installs.add(line.strip())
                
                for line in res.stdout.splitlines():
                    parts = line.strip().split(None, 2)
                    if len(parts) >= 2 and parts[0] == "ii":
                        pkg_ver = parts[1]
                        name = re.sub(r'-[0-9].*$', '', pkg_ver)
                        desc = parts[2] if len(parts) > 2 else ""
                        reason = 1 if name in auto_installs else 0
                        
                        p = Package(
                            name=name,
                            version=pkg_ver.split("-")[-1],
                            desc=desc,
                            isize=0,
                            reason=reason,
                            url=""
                        )
                        p.has_gui = False
                        p.is_font = name.lower().startswith("font-") or "font" in name.lower()
                        packages.append(p)
        except Exception:
            pass

        return packages

    def clean_cache(self, mode):
        return ["sudo", "xbps-remove", "-O"]

    def get_cache_size(self):
        try:
            res = subprocess.run(["du", "-sh", "/var/cache/xbps"], capture_output=True, text=True)
            if res.returncode == 0:
                return res.stdout.split()[0]
        except Exception:
            pass
        return "Unknown"

    def get_uninstall_cmd(self, packages):
        return ["xbps-remove", "-R"] + packages


class ApkBackend:
    """Alpine Linux APK Backend - Parses apk database directly for fast results."""
    def __init__(self):
        self.db_path = "/lib/apk/db/installed"
        self.world_path = "/etc/apk/world"
        if not os.path.exists(self.db_path):
            raise PackageManagerError("APK installed database not found at /lib/apk/db/installed")

    def get_installed_packages(self):
        manual = set()
        if os.path.exists(self.world_path):
            try:
                with open(self.world_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        clean = re.split(r'[<>=]', line)[0].strip()
                        if clean:
                            manual.add(clean)
            except Exception:
                pass

        packages = []
        try:
            with open(self.db_path, 'r', errors='ignore') as f:
                content = f.read()
        except Exception as e:
            raise PackageManagerError(f"Failed to read apk database: {e}")

        blocks = content.split("\n\n")
        for block in blocks:
            if not block.strip():
                continue
            
            pkg_data = {}
            for line in block.splitlines():
                if len(line) > 2 and line[1] == ':':
                    key = line[0]
                    val = line[2:]
                    pkg_data[key] = val

            name = pkg_data.get('P')
            if not name:
                continue

            version = pkg_data.get('V', '')
            desc = pkg_data.get('T', '')
            isize = int(pkg_data.get('I', 0))
            url = pkg_data.get('U', '')
            license_str = pkg_data.get('L', '')
            licenses = [l.strip() for l in license_str.split(",") if l.strip()]

            reason = 0 if name in manual else 1

            depends = []
            dep_str = pkg_data.get('D', '')
            if dep_str:
                for dep in dep_str.split():
                    if not dep.startswith("so:") and not dep.startswith("cmd:"):
                        clean_dep = re.split(r'[<>=]', dep)[0].strip()
                        if clean_dep:
                            depends.append(clean_dep)

            provides = []
            prov_str = pkg_data.get('p', '')
            if prov_str:
                for prov in prov_str.split():
                    clean_prov = re.split(r'[<>=]', prov)[0].strip()
                    if clean_prov:
                        provides.append(clean_prov)

            name_lower = name.lower()
            is_font = name_lower.startswith("font-") or "font" in name_lower
            has_gui = False

            p = Package(
                name=name,
                version=version,
                desc=desc,
                isize=isize,
                reason=reason,
                url=url,
                licenses=licenses,
                depends=depends,
                provides=provides,
                installdate=0
            )
            p.has_gui = has_gui
            p.is_font = is_font
            packages.append(p)

        return packages

    def clean_cache(self, mode):
        return ["sudo", "apk", "cache", "clean"]

    def get_cache_size(self):
        try:
            res = subprocess.run(["du", "-sh", "/var/cache/apk"], capture_output=True, text=True)
            if res.returncode == 0:
                return res.stdout.split()[0]
        except Exception:
            pass
        return "Unknown"

    def get_uninstall_cmd(self, packages):
        return ["apk", "del"] + packages


class GentooBackend:
    """Gentoo Linux Portage Backend - Parses local portage files under /var/db/pkg."""
    def __init__(self):
        self.db_path = "/var/db/pkg"
        self.world_path = "/var/lib/portage/world"
        if not os.path.exists(self.db_path):
            raise PackageManagerError("Gentoo package DB directory not found at /var/db/pkg")

    def get_installed_packages(self):
        manual = set()
        if os.path.exists(self.world_path):
            try:
                with open(self.world_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        clean = line.split('/')[-1].split(':')[0].strip()
                        if clean:
                            manual.add(clean)
            except Exception:
                pass

        packages = []
        try:
            categories = os.listdir(self.db_path)
        except Exception as e:
            raise PackageManagerError(f"Failed to read Gentoo DB: {e}")

        for cat in categories:
            cat_path = os.path.join(self.db_path, cat)
            if not os.path.isdir(cat_path):
                continue
            try:
                pkgs = os.listdir(cat_path)
            except Exception:
                continue

            for pkg_folder in pkgs:
                pkg_path = os.path.join(cat_path, pkg_folder)
                if not os.path.isdir(pkg_path):
                    continue
                  
                match = re.match(r'^([a-zA-Z0-9\-_+]+)-([0-9].*)$', pkg_folder)
                if not match:
                    continue
                name, version = match.groups()

                desc = self._read_meta_file(pkg_path, "DESCRIPTION")
                url = self._read_meta_file(pkg_path, "HOMEPAGE")
                license_str = self._read_meta_file(pkg_path, "LICENSE")
                licenses = [l.strip() for l in license_str.split() if l.strip()]
                  
                size_str = self._read_meta_file(pkg_path, "SIZE")
                isize = 0
                if size_str:
                    try:
                        isize = int(size_str)
                    except ValueError:
                        pass

                reason = 0 if name in manual or f"{cat}/{name}" in manual else 1

                depends = []
                dep_str = self._read_meta_file(pkg_path, "DEPEND")
                if dep_str:
                    for dep in dep_str.split():
                        clean_dep = re.sub(r'^[<>=!~]+', '', dep)
                        parts = clean_dep.split('/')
                        dep_pkg = parts[-1]
                        dep_pkg_clean = re.sub(r'-[0-9].*$', '', dep_pkg)
                        if dep_pkg_clean and not dep_pkg_clean.startswith("("):
                            depends.append(dep_pkg_clean)

                provides = []
                prov_str = self._read_meta_file(pkg_path, "PROVIDE")
                if prov_str:
                    provides = [p.strip() for p in prov_str.split() if p.strip()]

                has_gui = False
                contents_path = os.path.join(pkg_path, "CONTENTS")
                if os.path.exists(contents_path):
                    try:
                        with open(contents_path, 'r', errors='ignore') as cf:
                            for line in cf:
                                if "usr/share/applications/" in line and line.strip().endswith(".desktop"):
                                    has_gui = True
                                    break
                    except Exception:
                        pass

                name_lower = name.lower()
                is_font = name_lower.startswith("font-") or "font" in name_lower

                p = Package(
                    name=name,
                    version=version,
                    desc=desc,
                    isize=isize,
                    reason=reason,
                    url=url,
                    licenses=licenses,
                    depends=depends,
                    provides=provides,
                    installdate=0
                )
                p.has_gui = has_gui
                p.is_font = is_font
                packages.append(p)

        return packages

    def _read_meta_file(self, pkg_path, filename):
        fp = os.path.join(pkg_path, filename)
        if os.path.exists(fp):
            try:
                with open(fp, 'r', errors='ignore') as f:
                    return f.read().strip()
            except Exception:
                pass
        return ""

    def clean_cache(self, mode):
        if shutil.which("eclean"):
            return ["sudo", "eclean", "distfiles"]
        return None

    def get_cache_size(self):
        try:
            res = subprocess.run(["du", "-sh", "/var/cache/distfiles"], capture_output=True, text=True)
            if res.returncode == 0:
                return res.stdout.split()[0]
        except Exception:
            pass
        return "Unknown"

    def get_uninstall_cmd(self, packages):
        return ["emerge", "--depclean"] + packages


class NixBackend:
    """NixOS / Nix Package Manager Backend - Supports generations and GC cleanup."""
    def __init__(self):
        if not shutil.which("nix-store") and not shutil.which("nix-env"):
            raise PackageManagerError("Nix commands not found in PATH")

    def get_installed_packages(self):
        packages = []
        try:
            res = subprocess.run(["nix-env", "-q", "--json"], capture_output=True, text=True)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for name, info in data.items():
                    ver = info.get("version", "") if isinstance(info, dict) else ""
                    p = Package(
                        name=name,
                        version=ver,
                        desc="Nix user profile package",
                        isize=0,
                        reason=0,
                        url=""
                    )
                    p.has_gui = False
                    p.is_font = False
                    packages.append(p)
        except Exception:
            pass
        return packages

    def clean_cache(self, mode):
        # nix-collect-garbage deletes old generations and runs garbage collection
        if str(mode) == "2" or str(mode) == "4":
            return ["nix-collect-garbage", "-d"]
        return ["nix-collect-garbage"]

    def get_cache_size(self):
        try:
            res = subprocess.run(["du", "-sh", "/nix/store"], capture_output=True, text=True)
            if res.returncode == 0:
                return res.stdout.split()[0]
        except Exception:
            pass
        return "Unknown"

    def get_uninstall_cmd(self, packages):
        return ["nix-env", "-e"] + packages

# =====================================================================
# SYSTEM CLEANER CORE
# =====================================================================

class InraEngine:
    def __init__(self, ignore_file_path=None):
        self.ignore_file_path = ignore_file_path
        self.backend = self._detect_backend()
        self.pkg_dict = {}
        self.provisions_map = {}
        self.required_by = {}
        self.optional_required_by = {}
        self.critical = set()
        self.recursive_size_cache = {}

    def _detect_backend(self):
        if os.path.exists("/var/lib/pacman/local"):
            return PacmanBackend()
        elif os.path.exists("/var/lib/dpkg/status"):
            return AptBackend()
        elif os.path.exists("/var/db/xbps/pkgdb-0.3.plist") or shutil.which("xbps-query"):
            return XbpsBackend()
        elif os.path.exists("/lib/apk/db/installed"):
            return ApkBackend()
        elif os.path.exists("/var/db/pkg") and os.path.exists("/var/lib/portage/world"):
            return GentooBackend()
        elif shutil.which("nix-store") is not None:
            return NixBackend()
        elif shutil.which("rpm") is not None:
            return RpmBackend()
        else:
            raise PackageManagerError("No supported package manager detected on this system!")

    def get_package_manager_name(self):
        if isinstance(self.backend, PacmanBackend):
            return "Pacman (Arch Linux)"
        elif isinstance(self.backend, AptBackend):
            return "APT (Debian/Ubuntu)"
        elif isinstance(self.backend, RpmBackend):
            return "RPM/DNF (Fedora/RHEL)"
        elif isinstance(self.backend, XbpsBackend):
            return "XBPS (Void Linux)"
        elif isinstance(self.backend, ApkBackend):
            return "APK (Alpine Linux)"
        elif isinstance(self.backend, GentooBackend):
            return "Portage (Gentoo Linux)"
        elif isinstance(self.backend, NixBackend):
            return "Nix (NixOS)"
        return "Unknown"

    def _parse_dep_name(self, dep_spec):
        match = re.match(r'^([a-zA-Z0-9\-_+.:]+)', dep_spec)
        if match:
            return match.group(1)
        return dep_spec

    def load_system_state(self):
        self.recursive_size_cache = {}
        self.required_by = {}
        self.optional_required_by = {}
        self.provisions_map = {}
        
        packages = self.backend.get_installed_packages()
        self.pkg_dict = {p.name: p for p in packages}

        for p in packages:
            self.provisions_map[p.name] = {p.name}
            for prov in p.provides:
                prov_name = self._parse_dep_name(prov)
                if prov_name not in self.provisions_map:
                    self.provisions_map[prov_name] = set()
                self.provisions_map[prov_name].add(p.name)

        for p in packages:
            self.required_by[p.name] = set()
            self.optional_required_by[p.name] = set()

        for p in packages:
            for dep_spec in p.depends:
                dep_name = self._parse_dep_name(dep_spec)
                providers = self.provisions_map.get(dep_name, set())
                for prov in providers:
                    if prov in self.pkg_dict and prov != p.name:
                        self.required_by[prov].add(p.name)

            for dep_spec in p.optdepends:
                dep_name = self._parse_dep_name(dep_spec)
                providers = self.provisions_map.get(dep_name, set())
                for prov in providers:
                    if prov in self.pkg_dict and prov != p.name:
                        self.optional_required_by[prov].add(p.name)

        custom_ignore = set()
        if self.ignore_file_path and os.path.exists(self.ignore_file_path):
            try:
                with open(self.ignore_file_path, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            custom_ignore.add(line)
            except Exception as e:
                print(f"Warning: Could not read ignore file: {e}")

        seeds = {
            'sudo', 'bash', 'sh', 'coreutils', 'util-linux', 'systemd', 'networkmanager', 
            'openssh', 'grub', 'base', 'base-devel', 'apt', 'dpkg', 'rpm', 'dnf', 'setup',
            'filesystem', 'basesystem', 'kernel', 'nix', 'xbps', 'apk-tools'
        }
        seeds.update(custom_ignore)

        for p in packages:
            name = p.name
            if name.startswith('linux') and not name.endswith('-headers') and not name.endswith('-docs'):
                seeds.add(name)
            elif name.startswith('kernel') and not name.endswith('-headers') and not name.endswith('-devel'):
                seeds.add(name)

        self.critical = set()
        queue = list(seeds.intersection(self.pkg_dict.keys()))
        self.critical.update(queue)

        while queue:
            curr = queue.pop(0)
            pkg = self.pkg_dict[curr]
            for dep_spec in pkg.depends:
                dep_name = self._parse_dep_name(dep_spec)
                providers = self.provisions_map.get(dep_name, set())
                for prov in providers:
                    if prov in self.pkg_dict and prov not in self.critical:
                        self.critical.add(prov)
                        queue.append(prov)

        categories = {
            'strict_orphans': [],
            'optional_orphans': [],
            'explicit_gui': [],
            'explicit_dev': [],
            'explicit_fonts_themes': [],
            'explicit_cli_other': []
        }

        dev_keywords = re.compile(
            r'\b(devel|header|compiler|sdk|toolchain|debugging|headers|library|bindings|dev-tools)\b', 
            re.IGNORECASE
        )

        for p in packages:
            if p.name in self.critical:
                continue

            if len(self.required_by[p.name]) > 0:
                continue

            opt_for = self.optional_required_by[p.name]

            if p.reason == 1:
                if len(opt_for) == 0:
                    categories['strict_orphans'].append(p)
                else:
                    categories['optional_orphans'].append(p)
            else:
                is_dev = bool(dev_keywords.search(p.desc)) or p.name.endswith('-headers') or p.name.endswith('-devel') or p.name.endswith('-dev')
                is_font_theme = p.is_font or p.name.endswith('-theme') or p.name.endswith('-icon-theme') or 'theme' in p.name.lower()

                if p.has_gui:
                    categories['explicit_gui'].append(p)
                elif is_font_theme:
                    categories['explicit_fonts_themes'].append(p)
                elif is_dev:
                    categories['explicit_dev'].append(p)
                else:
                    categories['explicit_cli_other'].append(p)

        return categories

    def get_recursive_removals(self, pkg_name):
        removed = {pkg_name}
        q = [pkg_name]
        while q:
            curr_name = q.pop(0)
            curr_pkg = self.pkg_dict.get(curr_name)
            if not curr_pkg:
                continue
            for dep_spec in curr_pkg.depends:
                dep_name = self._parse_dep_name(dep_spec)
                providers = self.provisions_map.get(dep_name, set())
                for prov in providers:
                    if prov not in self.pkg_dict or prov in removed:
                        continue
                    dep_pkg = self.pkg_dict[prov]
                    if dep_pkg.reason == 1:
                        requirers = self.required_by[prov]
                        if requirers.issubset(removed):
                            removed.add(prov)
                            q.append(prov)
        return removed

    def get_recursive_removals_multi(self, pkg_names):
        removed = set(pkg_names)
        q = list(pkg_names)
        while q:
            curr_name = q.pop(0)
            curr_pkg = self.pkg_dict.get(curr_name)
            if not curr_pkg:
                continue
            for dep_spec in curr_pkg.depends:
                dep_name = self._parse_dep_name(dep_spec)
                providers = self.provisions_map.get(dep_name, set())
                for prov in providers:
                    if prov not in self.pkg_dict or prov in removed:
                        continue
                    dep_pkg = self.pkg_dict[prov]
                    if dep_pkg.reason == 1:
                        requirers = self.required_by[prov]
                        if requirers.issubset(removed):
                            removed.add(prov)
                            q.append(prov)
        return removed

    def get_recursive_size_cached(self, pkg_name):
        if pkg_name not in self.recursive_size_cache:
            removals = self.get_recursive_removals(pkg_name)
            total_size = sum(self.pkg_dict[name].isize for name in removals if name in self.pkg_dict)
            self.recursive_size_cache[pkg_name] = total_size
        return self.recursive_size_cache[pkg_name]


# =====================================================================
# HELPERS
# =====================================================================

def format_size(size_in_bytes):
    if size_in_bytes < 1024:
        return f"{size_in_bytes} B"
    elif size_in_bytes < 1024 * 1024:
        return f"{size_in_bytes / 1024:.2f} KB"
    elif size_in_bytes < 1024 * 1024 * 1024:
        return f"{size_in_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_in_bytes / (1024 * 1024 * 1024):.2f} GB"

def parse_size(size_str):
    if not size_str:
        return 0
    size_str = size_str.strip().upper()
    match = re.match(r'^([\d.]+)\s*([KMGT]B?|B)?$', size_str)
    if not match:
        raise ValueError(f"Invalid size specification: {size_str}")
    val, unit = match.groups()
    val = float(val)
    if not unit:
        return int(val)
    unit = unit.rstrip('B')
    multiplier = {
        'K': 1024,
        'M': 1024 * 1024,
        'G': 1024 * 1024 * 1024,
        'T': 1024 * 1024 * 1024 * 1024
    }
    return int(val * multiplier[unit])

def get_journal_size():
    try:
        res = subprocess.run(['journalctl', '--disk-usage'], capture_output=True, text=True, check=True)
        match = re.search(r'take up ([^\s]+)', res.stdout)
        if match:
            return match.group(1).replace('M', ' MB').replace('G', ' GB').replace('K', ' KB')
    except Exception:
        pass
    return "Unknown"

# =====================================================================
# TUI / KEYBOARD INPUT HELPERS
# =====================================================================

def getch():
    import sys
    import tty
    import termios
    fd = sys.stdin.fileno()
    try:
        old_settings = termios.tcgetattr(fd)
    except termios.error:
        return sys.stdin.read(1)
    try:
        tty.setraw(sys.stdin.fileno())
        ch = sys.stdin.read(1)
        if ch == '\x1b':
            ch2 = sys.stdin.read(1)
            if ch2 == '[':
                ch3 = sys.stdin.read(1)
                if ch3 == 'A':
                    return 'UP'
                elif ch3 == 'B':
                    return 'DOWN'
                elif ch3 == 'C':
                    return 'RIGHT'
                elif ch3 == 'D':
                    return 'LEFT'
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def clear_screen():
    os.system('clear' if os.name == 'posix' else 'cls')

def print_banner(pm_name=""):
    pm_info = f"Backend: {pm_name}" if pm_name else ""
    banner = f"""
{color_text("┌──────────────────────────────────────────────┐", CYAN)}
{color_text("│                   INRA                       │", CYAN + BOLD)}
{color_text("│    Smart, Universal Linux Package Purger     │", CYAN)}
{color_text("└──────────────────────────────────────────────┘", CYAN)} {color_text(pm_info, DIM)}"""
    print(banner)

# =====================================================================
# INTERACTIVE TUI CODE
# =====================================================================

def show_package_details(pkg, engine):
    clear_screen()
    print_banner(engine.get_package_manager_name())
    print(f"\n{color_text('Package Detailed Information', BOLD + BLUE)}")
    print("=" * 50)
    print(f"{color_text('Name', BOLD):<15}: {pkg.name}")
    print(f"{color_text('Version', BOLD):<15}: {pkg.version}")
    print(f"{color_text('Description', BOLD):<15}: {pkg.desc}")
    print(f"{color_text('URL', BOLD):<15}: {pkg.url}")
    print(f"{color_text('Licenses', BOLD):<15}: {', '.join(pkg.licenses) if pkg.licenses else 'N/A'}")
    print(f"{color_text('Groups', BOLD):<15}: {', '.join(pkg.groups) if pkg.groups else 'None'}")
    
    reason_str = "Explicitly installed" if pkg.reason == 0 else "Installed as dependency"
    print(f"{color_text('Install Reason', BOLD):<15}: {reason_str}")
    
    if pkg.installdate > 0:
        install_date = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(pkg.installdate))
        print(f"{color_text('Install Date', BOLD):<15}: {install_date}")
    
    print(f"{color_text('Installed Size', BOLD):<15}: {format_size(pkg.isize)}")
    
    rec_set = engine.get_recursive_removals(pkg.name)
    rec_size = sum(engine.pkg_dict[n].isize for n in rec_set if n in engine.pkg_dict)
    print(f"{color_text('Recursive Size', BOLD):<15}: {color_text(format_size(rec_size), GREEN)} ({len(rec_set)} packages total)")
    
    if len(rec_set) > 1:
        print(f"\n{color_text('Unused dependencies that will also be removed:', BOLD)}")
        for n in sorted(list(rec_set)):
            if n != pkg.name and n in engine.pkg_dict:
                print(f"  - {n} ({format_size(engine.pkg_dict[n].isize)})")
                
        opt_for = engine.optional_required_by.get(pkg.name, set())
        if opt_for:
            print(f"\n{color_text('Optional dependency for:', BOLD)}")
            print(f"  {', '.join(list(opt_for)[:10])}{'...' if len(opt_for) > 10 else ''}")
        
    print("-" * 50)
    print("Press any key to return...")
    getch()

def category_menu(cat_key, cat_label, pkgs, selections, engine):
    pkgs_sorted = sorted(pkgs, key=lambda p: engine.get_recursive_size_cached(p.name), reverse=True)
    
    page = 0
    page_size = 15
    cursor_idx = 0
    search_query = ""
    sort_mode = "rec_size"

    while True:
        filtered_pkgs = pkgs_sorted
        if search_query:
            q = search_query.lower()
            filtered_pkgs = [p for p in pkgs_sorted if q in p.name.lower() or q in p.desc.lower()]

        if sort_mode == "rec_size":
            filtered_pkgs = sorted(filtered_pkgs, key=lambda p: engine.get_recursive_size_cached(p.name), reverse=True)
        elif sort_mode == "size":
            filtered_pkgs = sorted(filtered_pkgs, key=lambda p: p.isize, reverse=True)
        elif sort_mode == "name":
            filtered_pkgs = sorted(filtered_pkgs, key=lambda p: p.name)
        elif sort_mode == "date":
            filtered_pkgs = sorted(filtered_pkgs, key=lambda p: p.installdate, reverse=True)

        clear_screen()
        print_banner(engine.get_package_manager_name())
        print(f"\n{color_text(cat_label, BOLD + BLUE)} | Sort: {sort_mode.upper()} | Search: {search_query or 'None'}")
        print("=" * 80)
        print("Navigation: " + color_text("Up/Down Arrows", BOLD) + " to hover | " + color_text("Space", BOLD) + " to toggle | " + color_text("I", BOLD) + " for info | " + color_text("/", BOLD) + " to search")
        print("Commands  : " + color_text("S", BOLD) + " to cycle sort | " + color_text("A", BOLD) + " select all | " + color_text("C", BOLD) + " clear all | " + color_text("B", BOLD) + " back")
        print("-" * 80)
        
        total_pages = (len(filtered_pkgs) - 1) // page_size + 1 if filtered_pkgs else 1
        if page >= total_pages:
            page = total_pages - 1
        if page < 0:
            page = 0
            
        start_idx = page * page_size
        end_idx = min(start_idx + page_size, len(filtered_pkgs))
        
        if cursor_idx >= len(filtered_pkgs):
            cursor_idx = max(0, len(filtered_pkgs) - 1)
        
        print(f"    {'Package Name':<28} {'Size':<10} {'Rec. Size':<10} {'Description'}")
        print("-" * 80)
        
        for idx in range(start_idx, end_idx):
            p = filtered_pkgs[idx]
            is_hover = (idx == cursor_idx)
            checked = "[X]" if selections.get(p.name, False) else "[ ]"
            checked_color = GREEN if checked == "[X]" else WHITE
            
            prefix = color_text(" >  ", CYAN) if is_hover else "    "
            rec_size = engine.get_recursive_size_cached(p.name)
            desc = p.desc
            if len(desc) > 30:
                desc = desc[:27] + "..."
                
            line_str = f"{prefix}{color_text(checked, checked_color):<3} {p.name:<28} {format_size(p.isize):<10} {format_size(rec_size):<10} {desc}"
            if is_hover:
                print(color_text(line_str, BOLD + WHITE))
            else:
                print(line_str)
            
        print("-" * 80)
        print(f"Page {page+1} of {total_pages} | Packages {start_idx+1}-{end_idx} of {len(filtered_pkgs)}")
        print("-" * 80)
        
        key = getch()
        if not key:
            continue
            
        if key == 'UP':
            if cursor_idx > 0:
                cursor_idx -= 1
                page = cursor_idx // page_size
        elif key == 'DOWN':
            if cursor_idx < len(filtered_pkgs) - 1:
                cursor_idx += 1
                page = cursor_idx // page_size
        elif key == ' ':
            if filtered_pkgs:
                name = filtered_pkgs[cursor_idx].name
                selections[name] = not selections.get(name, False)
        elif key.lower() == 'i':
            if filtered_pkgs:
                show_package_details(filtered_pkgs[cursor_idx], engine)
        elif key == '/':
            sys.stdout.write("\rSearch (Esc to cancel): ")
            sys.stdout.flush()
            import termios
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
            try:
                q = input().strip()
                search_query = q
                cursor_idx = 0
                page = 0
            except KeyboardInterrupt:
                search_query = ""
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
        elif key.lower() == 's':
            sorts = ["rec_size", "size", "name", "date"]
            curr_sort_idx = sorts.index(sort_mode)
            sort_mode = sorts[(curr_sort_idx + 1) % len(sorts)]
        elif key.lower() == 'a':
            for p in filtered_pkgs:
                selections[p.name] = True
        elif key.lower() == 'c':
            for p in filtered_pkgs:
                selections[p.name] = False
        elif key.lower() == 'b' or key == '\x1b':
            break

def clean_cache_menu(engine):
    while True:
        clear_screen()
        print_banner(engine.get_package_manager_name())
        print(f"\n{color_text('Package Cache Management', BOLD + BLUE)}")
        print("=" * 40)
        print(f"Current Cache Size: {color_text(engine.backend.get_cache_size(), GREEN + BOLD)}")
        print("-" * 40)
        print("[1] Prune old cache (keep latest 3 versions - safe default)")
        print("[2] Prune old cache aggressively (keep only the latest version)")
        print("[3] Remove all cached packages for uninstalled apps (safe)")
        print("[4] Clear cache completely (removes all cached versions)")
        print("[B] Back to main menu")
        print("-" * 40)
        
        choice = input("Enter option (1-4, B): ").strip().upper()
        if choice == 'B':
            break
        elif choice in ['1', '2', '3', '4']:
            cmd = engine.backend.clean_cache(choice)
            if cmd:
                print(color_text(f"\nRunning cache cleaning command: {' '.join(cmd)}", YELLOW))
                try:
                    subprocess.run(cmd, check=True)
                except Exception as e:
                    print(color_text(f"Error running cleanup command: {e}", RED))
            else:
                print(color_text("Action not supported by current package manager backend.", YELLOW))
            input("\nPress Enter to continue...")

def clean_journal_menu(engine):
    while True:
        clear_screen()
        print_banner(engine.get_package_manager_name())
        current_size = get_journal_size()
        print(f"\n{color_text('Systemd Journal Logs Management', BOLD + BLUE)}")
        print("=" * 40)
        print(f"Current disk usage: {color_text(current_size, GREEN + BOLD)}")
        print("-" * 40)
        print("[1] Vacuum logs older than 2 days (recommended)")
        print("[2] Vacuum logs older than 7 days")
        print("[3] Limit log size to 100MB")
        print("[4] Limit log size to 500MB")
        print("[B] Back to main menu")
        print("-" * 40)
        
        choice = input("Enter option (1-4, B): ").strip().upper()
        if choice == 'B':
            break
        elif choice == '1':
            print(color_text("\nVacuuming logs older than 2 days...", YELLOW))
            subprocess.run(['sudo', 'journalctl', '--vacuum-time=2d'])
            input("\nPress Enter to continue...")
        elif choice == '2':
            print(color_text("\nVacuuming logs older than 7 days...", YELLOW))
            subprocess.run(['sudo', 'journalctl', '--vacuum-time=7d'])
            input("\nPress Enter to continue...")
        elif choice == '3':
            print(color_text("\nVacuuming logs to limit size to 100MB...", YELLOW))
            subprocess.run(['sudo', 'journalctl', '--vacuum-size=100M'])
            input("\nPress Enter to continue...")
        elif choice == '4':
            print(color_text("\nVacuuming logs to limit size to 500MB...", YELLOW))
            subprocess.run(['sudo', 'journalctl', '--vacuum-size=500M'])
            input("\nPress Enter to continue...")

def run_cleanup_flow(selections, categories, engine):
    selected_pkgs = [p for cat in categories.values() for p in cat if selections.get(p.name, False)]
    if not selected_pkgs:
        print(f"\n{color_text('No packages selected for removal!', YELLOW)}")
        time.sleep(1.5)
        return
        
    clear_screen()
    print_banner(engine.get_package_manager_name())
    print(f"\n{color_text('Cleanup Review', BOLD + RED)}")
    print("=" * 40)
    
    all_removed = engine.get_recursive_removals_multi([p.name for p in selected_pkgs])
    
    print(f"The following {len(selected_pkgs)} packages were explicitly selected:")
    for p in sorted(selected_pkgs, key=lambda x: x.name):
        print(f"  - {p.name} ({format_size(p.isize)})")
        
    dep_removed = all_removed - {p.name for p in selected_pkgs}
    if dep_removed:
        print(f"\nThe following {len(dep_removed)} unused dependencies will also be removed:")
        for name in sorted(list(dep_removed)):
            if name in engine.pkg_dict:
                print(f"  - {name} ({format_size(engine.pkg_dict[name].isize)})")
            else:
                print(f"  - {name}")
            
    total_size_freed = sum(engine.pkg_dict[name].isize for name in all_removed if name in engine.pkg_dict)
    print("\n" + "-" * 40)
    print(f"Total packages to remove: {len(all_removed)}")
    print(f"Total space to be freed : {color_text(format_size(total_size_freed), GREEN + BOLD)}")
    print("-" * 40)
    
    confirm = input("Do you want to proceed with removal? [y/N]: ").strip().lower()
    if confirm == 'y':
        raw_cmd = engine.backend.get_uninstall_cmd(list(sorted([p.name for p in selected_pkgs])))
        cmd_list = ['sudo'] + raw_cmd
        print(f"\nRunning command: {' '.join(cmd_list)}")
        try:
            subprocess.run(cmd_list, check=True)
            for name in all_removed:
                if name in selections:
                    selections[name] = False
            print(f"\n{color_text('Packages successfully removed!', GREEN)}")
            print("Reloading database...")
            time.sleep(2)
            
            new_cats = engine.load_system_state()
            categories.clear()
            categories.update(new_cats)
            still_installed = {p.name for cat in categories.values() for p in cat}
            for k in list(selections.keys()):
                if k not in still_installed:
                    selections.pop(k)
        except subprocess.CalledProcessError:
            print(f"\n{color_text('Error: package manager cleanup command failed.', RED)}")
            input("\nPress Enter to return...")
    else:
        print("Removal cancelled.")
        time.sleep(1.5)

def interactive_loop(categories, engine):
    selections = {}
    
    while True:
        clear_screen()
        print_banner(engine.get_package_manager_name())
        
        print(f"\n{color_text('Summary of Potential Space Savings:', BOLD)}")
        print("-" * 55)
        
        keys = ['strict_orphans', 'optional_orphans', 'explicit_gui', 'explicit_dev', 'explicit_fonts_themes', 'explicit_cli_other']
        labels = {
            'strict_orphans': "Orphan Packages (Strict)",
            'optional_orphans': "Orphan Packages (Optional)",
            'explicit_gui': "Unused Explicit GUI Apps",
            'explicit_dev': "Unused Explicit Dev/Build Tools",
            'explicit_fonts_themes': "Unused Explicit Fonts & Themes",
            'explicit_cli_other': "Unused Explicit CLI & Others"
        }
        
        for idx, key in enumerate(keys, start=1):
            pkgs = categories[key]
            total_size = sum(p.isize for p in pkgs)
            selected_in_cat = sum(1 for p in pkgs if selections.get(p.name, False))
            
            sel_str = f"({selected_in_cat} selected)" if selected_in_cat > 0 else ""
            print(f"[{idx}] {labels[key]:<32} : {len(pkgs):>4} pkgs, {format_size(total_size):>10} {color_text(sel_str, GREEN)}")
            
        print(f"[7] Package Cache Management         : Manage / Clean")
        journal_size = get_journal_size()
        print(f"[8] Systemd Journal Logs             : {journal_size:>10} available")
        
        print("-" * 55)
        
        selected_pkgs = [p for cat in categories.values() for p in cat if selections.get(p.name, False)]
        if selected_pkgs:
            all_removed = engine.get_recursive_removals_multi([p.name for p in selected_pkgs])
            total_size_freed = sum(engine.pkg_dict[name].isize for name in all_removed if name in engine.pkg_dict)
            print(f"Selected: {len(selected_pkgs)} packages ({len(all_removed)} total including dependencies)")
            print(f"Total Space to Free: {color_text(format_size(total_size_freed), RED + BOLD)}")
            print("-" * 55)
            
        print(f"{color_text('[R] Run Cleanup', GREEN + BOLD)}   {color_text('[Q] Quit', YELLOW)}")
        print()
        
        choice = input("Enter choice (1-8, R, Q): ").strip().upper()
        if choice == 'Q':
            break
        elif choice == 'R':
            run_cleanup_flow(selections, categories, engine)
        elif choice in ['1', '2', '3', '4', '5', '6']:
            key = keys[int(choice) - 1]
            category_menu(key, labels[key], categories[key], selections, engine)
        elif choice == '7':
            clean_cache_menu(engine)
        elif choice == '8':
            clean_journal_menu(engine)

# =====================================================================
# DRY RUN / CLI / JSON REPORT CODE
# =====================================================================

def run_dry_run_report(categories, min_size, engine):
    print("==================================================")
    print(f"INRA - Dry Run Report (Backend: {engine.get_package_manager_name()})")
    print("==================================================")
    
    keys = ['strict_orphans', 'optional_orphans', 'explicit_gui', 'explicit_dev', 'explicit_fonts_themes', 'explicit_cli_other']
    labels = {
        'strict_orphans': "Orphan Packages (Strict)",
        'optional_orphans': "Orphan Packages (Optional)",
        'explicit_gui': "Unused Explicit GUI Applications",
        'explicit_dev': "Unused Explicit Dev/Build Tools",
        'explicit_fonts_themes': "Unused Explicit Fonts & Themes",
        'explicit_cli_other': "Unused Explicit CLI & Others"
    }
    
    grand_total_packages = 0
    grand_total_size = 0
    
    for key in keys:
        pkgs = categories[key]
        filtered_pkgs = [p for p in pkgs if engine.get_recursive_size_cached(p.name) >= min_size]
        if not filtered_pkgs:
            continue
            
        print(f"\n{labels[key]} ({len(filtered_pkgs)} packages):")
        print("-" * 50)
        
        for p in sorted(filtered_pkgs, key=lambda x: engine.get_recursive_size_cached(x.name), reverse=True):
            rec_size = engine.get_recursive_size_cached(p.name)
            grand_total_packages += 1
            grand_total_size += p.isize
            
            print(f"  - {p.name:<25} [Size: {format_size(p.isize):>10} | Rec. Size: {format_size(rec_size):>10}]")
            print(f"    Desc: {p.desc}")
            
    print("\n==================================================")
    print(f"Total Candidates: {grand_total_packages} packages")
    print(f"Total Potential Savings: {format_size(grand_total_size)} (approx, excluding shared dependencies)")
    print("==================================================")

def run_json_output(categories, engine):
    output_data = {}
    for cat_key, pkgs in categories.items():
        output_data[cat_key] = []
        for p in pkgs:
            removals = engine.get_recursive_removals(p.name)
            output_data[cat_key].append({
                'name': p.name,
                'version': p.version,
                'description': p.desc,
                'installed_size': p.isize,
                'recursive_size': sum(engine.pkg_dict[name].isize for name in removals if name in engine.pkg_dict),
                'recursive_packages': list(removals),
                'install_date': p.installdate,
                'url': p.url
            })
    print(json.dumps(output_data, indent=2))

# =====================================================================
# LOCAL WEB GUI FRONTEND
# =====================================================================

HTML_CONTENT = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Inra - System Cleaner</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #080b11;
            --card-bg: rgba(18, 26, 41, 0.6);
            --border-color: rgba(255, 255, 255, 0.07);
            --primary: #00d2ff;
            --primary-glow: rgba(0, 210, 255, 0.25);
            --success: #00e676;
            --danger: #ff1744;
            --text-main: #f1f5f9;
            --text-muted: #94a3b8;
            --font-family: 'Outfit', sans-serif;
            --sidebar-width: 280px;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            background-color: var(--bg-color);
            background-image: radial-gradient(circle at 10% 20%, rgba(0, 210, 255, 0.05) 0%, transparent 40%),
                              radial-gradient(circle at 90% 80%, rgba(0, 230, 118, 0.03) 0%, transparent 40%);
            color: var(--text-main);
            font-family: var(--font-family);
            min-height: 100vh;
            display: flex;
            overflow-x: hidden;
        }

        /* Sidebar Navigation */
        .sidebar {
            width: var(--sidebar-width);
            background: var(--card-bg);
            border-right: 1px solid var(--border-color);
            backdrop-filter: blur(15px);
            padding: 2rem 1.5rem;
            display: flex;
            flex-direction: column;
            position: fixed;
            height: 100vh;
            z-index: 10;
        }

        .brand {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 2.5rem;
        }

        .brand-logo {
            font-size: 2.2rem;
            font-weight: 700;
            background: linear-gradient(135deg, var(--primary), var(--success));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            letter-spacing: -1px;
        }

        .brand-subtitle {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 2px;
            font-weight: 600;
        }

        .nav-list {
            list-style: none;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .nav-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.9rem 1.2rem;
            border-radius: 12px;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            color: var(--text-muted);
            border: 1px solid transparent;
            font-weight: 500;
        }

        .nav-item:hover {
            color: var(--text-main);
            background: rgba(255, 255, 255, 0.03);
        }

        .nav-item.active {
            color: var(--text-main);
            background: linear-gradient(135deg, rgba(0, 210, 255, 0.1), rgba(0, 230, 118, 0.05));
            border-color: rgba(0, 210, 255, 0.3);
            box-shadow: 0 4px 20px rgba(0, 210, 255, 0.05);
        }

        .nav-badge {
            font-size: 0.75rem;
            padding: 2px 8px;
            border-radius: 20px;
            background: rgba(255, 255, 255, 0.08);
            color: var(--text-main);
            font-weight: 600;
        }

        .nav-item.active .nav-badge {
            background: var(--primary);
            color: #000;
        }

        /* Main Content Panel */
        .main-content {
            margin-left: var(--sidebar-width);
            flex: 1;
            padding: 2.5rem;
            display: flex;
            flex-direction: column;
            gap: 2.5rem;
            max-width: 1400px;
        }

        /* Header Statistics */
        .header-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 1.5rem;
        }

        .stat-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            backdrop-filter: blur(10px);
            display: flex;
            flex-direction: column;
            gap: 8px;
            position: relative;
            overflow: hidden;
            transition: transform 0.3s ease;
        }

        .stat-card:hover {
            transform: translateY(-2px);
        }

        .stat-card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 3px;
            background: linear-gradient(90deg, var(--primary), var(--success));
        }

        .stat-label {
            font-size: 0.85rem;
            color: var(--text-muted);
            font-weight: 500;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .stat-val {
            font-size: 1.8rem;
            font-weight: 700;
        }

        .stat-desc {
            font-size: 0.8rem;
            color: var(--text-muted);
        }

        .glow-green {
            color: var(--success);
            text-shadow: 0 0 10px rgba(0, 230, 118, 0.3);
        }

        .glow-blue {
            color: var(--primary);
            text-shadow: 0 0 10px rgba(0, 210, 255, 0.3);
        }

        /* Package List Section */
        .packages-panel {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            backdrop-filter: blur(10px);
            display: flex;
            flex-direction: column;
            overflow: hidden;
            flex: 1;
        }

        .panel-header {
            padding: 1.5rem 2rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 1rem;
        }

        .panel-title {
            font-size: 1.25rem;
            font-weight: 600;
        }

        .panel-actions {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .search-bar {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            padding: 0.55rem 1rem;
            color: var(--text-main);
            font-family: var(--font-family);
            font-size: 0.9rem;
            outline: none;
            width: 240px;
            transition: all 0.3s ease;
        }

        .search-bar:focus {
            border-color: var(--primary);
            box-shadow: 0 0 10px var(--primary-glow);
            width: 280px;
        }

        .btn {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            padding: 0.55rem 1.2rem;
            border-radius: 10px;
            font-family: var(--font-family);
            font-size: 0.9rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn:hover {
            background: rgba(255, 255, 255, 0.09);
        }

        .btn-primary {
            background: linear-gradient(135deg, var(--primary), var(--success));
            border: none;
            color: #05080e;
            font-weight: 600;
            box-shadow: 0 4px 15px rgba(0, 210, 255, 0.2);
        }

        .btn-primary:hover {
            background: linear-gradient(135deg, #00b8e6, #00cc66);
            box-shadow: 0 6px 20px rgba(0, 210, 255, 0.3);
            transform: translateY(-1px);
        }

        .select-sort {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border-color);
            border-radius: 10px;
            color: var(--text-main);
            padding: 0.55rem 1rem;
            font-family: var(--font-family);
            font-size: 0.9rem;
            outline: none;
            cursor: pointer;
        }

        /* Package List Table */
        .table-container {
            max-height: 520px;
            overflow-y: auto;
        }

        table {
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }

        th {
            padding: 1rem 2rem;
            color: var(--text-muted);
            font-weight: 600;
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border-bottom: 1px solid var(--border-color);
            background: rgba(255, 255, 255, 0.01);
        }

        td {
            padding: 1.1rem 2rem;
            border-bottom: 1px solid var(--border-color);
            font-size: 0.95rem;
            color: var(--text-main);
        }

        tr:last-child td {
            border-bottom: none;
        }

        tr:hover td {
            background: rgba(255, 255, 255, 0.01);
        }

        .pkg-checkbox {
            cursor: pointer;
            width: 18px;
            height: 18px;
            accent-color: var(--success);
        }

        .pkg-name {
            font-weight: 600;
            color: var(--text-main);
        }

        .pkg-desc {
            color: var(--text-muted);
            max-width: 450px;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .pkg-info-btn {
            background: transparent;
            border: none;
            color: var(--primary);
            cursor: pointer;
            font-weight: 500;
            font-size: 0.9rem;
        }

        .pkg-info-btn:hover {
            text-decoration: underline;
        }

        /* Footer Sticky Action Bar */
        .action-bar {
            position: fixed;
            bottom: 2rem;
            left: calc(var(--sidebar-width) + 2.5rem);
            right: 2.5rem;
            background: rgba(11, 15, 25, 0.85);
            border: 1px solid rgba(0, 210, 255, 0.2);
            backdrop-filter: blur(20px);
            padding: 1.2rem 2rem;
            border-radius: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5), 0 0 20px rgba(0, 210, 255, 0.05);
            z-index: 5;
            transition: all 0.3s ease;
            transform: translateY(120px);
        }

        .action-bar.visible {
            transform: translateY(0);
        }

        .action-text {
            font-weight: 500;
        }

        .action-space {
            color: var(--success);
            font-weight: 700;
            font-size: 1.1rem;
        }

        /* Modal popup */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: rgba(4, 6, 10, 0.8);
            backdrop-filter: blur(8px);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 100;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.3s ease;
        }

        .modal-overlay.active {
            opacity: 1;
            pointer-events: all;
        }

        .modal {
            background: #0f172a;
            border: 1px solid var(--border-color);
            border-radius: 20px;
            width: 600px;
            max-width: 90%;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-shadow: 0 20px 40px rgba(0,0,0,0.6);
            transform: scale(0.9);
            transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
        }

        .modal-overlay.active .modal {
            transform: scale(1);
        }

        .modal-header {
            padding: 1.5rem 2rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .modal-title {
            font-size: 1.2rem;
            font-weight: 600;
        }

        .modal-close {
            background: transparent;
            border: none;
            color: var(--text-muted);
            font-size: 1.5rem;
            cursor: pointer;
        }

        .modal-close:hover {
            color: var(--text-main);
        }

        .modal-body {
            padding: 2rem;
            overflow-y: auto;
            max-height: 400px;
            display: flex;
            flex-direction: column;
            gap: 1.2rem;
        }

        .modal-footer {
            padding: 1.2rem 2rem;
            border-top: 1px solid var(--border-color);
            display: flex;
            justify-content: flex-end;
            gap: 12px;
            background: rgba(0, 0, 0, 0.15);
        }

        .detail-row {
            display: flex;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            padding-bottom: 0.8rem;
        }

        .detail-row:last-child {
            border-bottom: none;
        }

        .detail-lbl {
            width: 160px;
            color: var(--text-muted);
            font-weight: 500;
        }

        .detail-val {
            flex: 1;
        }

        .dependency-list {
            margin-top: 5px;
            padding-left: 15px;
            color: var(--text-muted);
            font-size: 0.9rem;
        }

        /* Utilities cleaning cards */
        .clean-actions-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
        }

        .clean-card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 16px;
            padding: 1.5rem;
            display: flex;
            flex-direction: column;
            gap: 15px;
        }

        .clean-card-title {
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--primary);
        }

        .clean-options {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .clean-opt {
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
            font-size: 0.9rem;
        }

        .clean-opt input {
            cursor: pointer;
        }

        /* Live log output console */
        .console-log {
            background: #020617;
            border: 1px solid #1e293b;
            font-family: monospace;
            padding: 1rem;
            border-radius: 10px;
            max-height: 200px;
            overflow-y: auto;
            color: #38bdf8;
            font-size: 0.85rem;
            white-space: pre-wrap;
        }
    </style>
</head>
<body>

    <!-- Sidebar -->
    <div class="sidebar">
        <div class="brand">
            <div>
                <div class="brand-logo">INRA</div>
                <div class="brand-subtitle">System Purger</div>
            </div>
        </div>
        <ul class="nav-list">
            <li class="nav-item active" onclick="switchCategory('strict_orphans', this)">
                <span>Strict Orphans</span>
                <span class="nav-badge" id="badge-strict_orphans">0</span>
            </li>
            <li class="nav-item" onclick="switchCategory('optional_orphans', this)">
                <span>Optional Orphans</span>
                <span class="nav-badge" id="badge-optional_orphans">0</span>
            </li>
            <li class="nav-item" onclick="switchCategory('explicit_gui', this)">
                <span>GUI Applications</span>
                <span class="nav-badge" id="badge-explicit_gui">0</span>
            </li>
            <li class="nav-item" onclick="switchCategory('explicit_dev', this)">
                <span>Development Tools</span>
                <span class="nav-badge" id="badge-explicit_dev">0</span>
            </li>
            <li class="nav-item" onclick="switchCategory('explicit_fonts_themes', this)">
                <span>Fonts & Themes</span>
                <span class="nav-badge" id="badge-explicit_fonts_themes">0</span>
            </li>
            <li class="nav-item" onclick="switchCategory('explicit_cli_other', this)">
                <span>CLI & Other Tools</span>
                <span class="nav-badge" id="badge-explicit_cli_other">0</span>
            </li>
            <li class="nav-item" onclick="switchCategory('utilities', this)" style="margin-top: 1.5rem; border-top: 1px solid var(--border-color); padding-top: 1.5rem;">
                <span>System Utilities</span>
                <span class="nav-badge" style="background: transparent; color: var(--primary);">⚙</span>
            </li>
        </ul>
    </div>

    <!-- Main Content -->
    <div class="main-content">
        <!-- Stats -->
        <div class="header-stats">
            <div class="stat-card">
                <span class="stat-label">OS / Package Manager</span>
                <span class="stat-val glow-blue" id="stat-pm">Scanning...</span>
                <span class="stat-desc">System detected</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">Scan Candidates</span>
                <span class="stat-val" id="stat-count">0</span>
                <span class="stat-desc">Unused packages detected</span>
            </div>
            <div class="stat-card">
                <span class="stat-label">Total Potential Savings</span>
                <span class="stat-val glow-green" id="stat-size">0 B</span>
                <span class="stat-desc">Space can be reclaimed</span>
            </div>
        </div>

        <!-- Main Categories / Tools Panel -->
        <div class="packages-panel" id="packages-panel-view">
            <div class="panel-header">
                <div class="panel-title" id="current-cat-title">Orphan Packages (Strict)</div>
                <div class="panel-actions">
                    <input type="text" class="search-bar" id="search-input" placeholder="Search package..." oninput="handleSearch()">
                    <select class="select-sort" id="sort-select" onchange="handleSort()">
                        <option value="rec_size">Recursive Size</option>
                        <option value="size">Individual Size</option>
                        <option value="name">Name (A-Z)</option>
                        <option value="date">Install Date</option>
                    </select>
                    <button class="btn" onclick="toggleSelectAll(true)">Select All</button>
                    <button class="btn" onclick="toggleSelectAll(false)">Clear All</button>
                </div>
            </div>
            <div class="table-container">
                <table>
                    <thead>
                        <tr>
                            <th style="width: 50px;">Select</th>
                            <th style="width: 250px;">Package Name</th>
                            <th style="width: 120px;">Size</th>
                            <th style="width: 120px;">Rec. Size</th>
                            <th>Description</th>
                            <th style="width: 100px; text-align: right;">Details</th>
                        </tr>
                    </thead>
                    <tbody id="package-list-tbody">
                        <!-- Packages populated by JS -->
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Utilities View (Hidden by default) -->
        <div class="clean-actions-grid" id="utilities-panel-view" style="display: none;">
            <div class="clean-card">
                <div class="clean-card-title">Package Manager Cache Cleaner</div>
                <p class="stat-desc">Cleaning the package cache will release disk space containing older downloaded packages.</p>
                <div class="detail-row">
                    <span class="detail-lbl">Current Cache Size:</span>
                    <span class="detail-val glow-green" id="utils-cache-size" style="font-weight:600;">Scanning...</span>
                </div>
                <div class="clean-options">
                    <label class="clean-opt">
                        <input type="radio" name="cache-mode" value="1" checked>
                        <span>Prune old packages (keep latest 3 versions - safe default)</span>
                    </label>
                    <label class="clean-opt">
                        <input type="radio" name="cache-mode" value="2">
                        <span>Aggressive prune (keep only the latest version)</span>
                    </label>
                    <label class="clean-opt">
                        <input type="radio" name="cache-mode" value="3">
                        <span>Remove cached packages for uninstalled apps</span>
                    </label>
                    <label class="clean-opt">
                        <input type="radio" name="cache-mode" value="4">
                        <span>Clear cache completely (removes all cached files)</span>
                    </label>
                </div>
                <button class="btn btn-primary" onclick="runCacheClean()" style="justify-content: center;">Clean Package Cache</button>
            </div>

            <div class="clean-card">
                <div class="clean-card-title">Systemd Journal Logs Vacuum</div>
                <p class="stat-desc">Systemd logs accumulate over time. Truncating old logs releases disk space safely.</p>
                <div class="detail-row">
                    <span class="detail-lbl">Current Journal Size:</span>
                    <span class="detail-val glow-green" id="utils-journal-size" style="font-weight:600;">Scanning...</span>
                </div>
                <div class="clean-options">
                    <label class="clean-opt">
                        <input type="radio" name="journal-mode" value="1" checked>
                        <span>Vacuum logs older than 2 days</span>
                    </label>
                    <label class="clean-opt">
                        <input type="radio" name="journal-mode" value="2">
                        <span>Vacuum logs older than 7 days</span>
                    </label>
                    <label class="clean-opt">
                        <input type="radio" name="journal-mode" value="3">
                        <span>Limit journal log size to 100 MB</span>
                    </label>
                    <label class="clean-opt">
                        <input type="radio" name="journal-mode" value="4">
                        <span>Limit journal log size to 500 MB</span>
                    </label>
                </div>
                <button class="btn btn-primary" onclick="runJournalVacuum()" style="justify-content: center;">Vacuum Journal Logs</button>
            </div>
        </div>
    </div>

    <!-- Floating Action Bar -->
    <div class="action-bar" id="floating-action-bar">
        <div class="action-text">
            Selected: <span id="selected-count">0</span> packages | Total Reclaimed Space: <span class="action-space" id="selected-space">0 B</span>
        </div>
        <button class="btn btn-primary" onclick="openCleanupReview()">Purge Selected Packages</button>
    </div>

    <!-- Package Detail Modal -->
    <div class="modal-overlay" id="detail-modal-overlay" onclick="closeModal('detail-modal-overlay')">
        <div class="modal" onclick="event.stopPropagation()">
            <div class="modal-header">
                <div class="modal-title" id="modal-pkg-name">Package Details</div>
                <button class="modal-close" onclick="closeModal('detail-modal-overlay')">&times;</button>
            </div>
            <div class="modal-body" id="modal-pkg-body">
                <!-- Populated dynamically -->
            </div>
            <div class="modal-footer">
                <button class="btn" onclick="closeModal('detail-modal-overlay')">Close</button>
            </div>
        </div>
    </div>

    <!-- Cleanup Review Modal -->
    <div class="modal-overlay" id="review-modal-overlay" onclick="closeModal('review-modal-overlay')">
        <div class="modal" onclick="event.stopPropagation()">
            <div class="modal-header">
                <div class="modal-title">Confirm Package Purge</div>
                <button class="modal-close" onclick="closeModal('review-modal-overlay')">&times;</button>
            </div>
            <div class="modal-body">
                <p>Are you sure you want to uninstall the selected packages?</p>
                <div id="cleanup-review-stats" style="font-weight: 500;"></div>
                <p class="stat-desc">This action runs the package manager command to remove selected items and their unused dependencies recursively.</p>
                <div class="console-log" id="cleanup-console" style="display: none;"></div>
            </div>
            <div class="modal-footer" id="review-modal-footer">
                <button class="btn" id="btn-cancel-cleanup" onclick="closeModal('review-modal-overlay')">Cancel</button>
                <button class="btn btn-primary" id="btn-confirm-cleanup" onclick="executePurge()">Proceed with Purge</button>
            </div>
        </div>
    </div>

    <script>
        let currentCategory = 'strict_orphans';
        let categoriesData = {};
        let selectedPackages = {}; // pkgName -> boolean
        let pmBackend = '';
        let cacheSize = 'Unknown';
        let journalSize = 'Unknown';

        window.onload = async function() {
            try {
                await refreshData();
            } catch (err) {
                console.error("Initialization error:", err);
            }
            try {
                switchCategory('strict_orphans', document.querySelector('.nav-item'));
            } catch (err) {
                console.error("Navigation error:", err);
            }
        }

        async function refreshData() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                
                if (data.error) {
                    console.error("Backend Error:", data.error);
                    document.getElementById('stat-pm').innerText = "Error: " + data.error;
                    return;
                }

                categoriesData = data.categories || {};
                pmBackend = data.package_manager || "Unknown";
                cacheSize = data.cache_size || "Unknown";
                journalSize = data.journal_size || "Unknown";

                document.getElementById('stat-pm').innerText = pmBackend;
                document.getElementById('utils-cache-size').innerText = cacheSize;
                document.getElementById('utils-journal-size').innerText = journalSize;

                let totalCount = 0;
                let totalBytes = 0;

                for (const cat in categoriesData) {
                    if (!categoriesData[cat]) continue;
                    const count = categoriesData[cat].length;
                    const badge = document.getElementById(`badge-${cat}`);
                    if (badge) badge.innerText = count;

                    totalCount += count;
                    categoriesData[cat].forEach(p => {
                        totalBytes += (p.installed_size || 0);
                    });
                }
                document.getElementById('stat-count').innerText = totalCount;
                document.getElementById('stat-size').innerText = formatSize(totalBytes);

                updateActionBar();
            } catch (e) {
                console.error("Failed to load status:", e);
                document.getElementById('stat-pm').innerText = "Connection Failed: " + e.message;
            }
        }

        function switchCategory(cat, element) {
            currentCategory = cat;
            
            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            if (element) element.classList.add('active');

            if (cat === 'utilities') {
                document.getElementById('packages-panel-view').style.display = 'none';
                document.getElementById('utilities-panel-view').style.display = 'flex';
                return;
            }

            document.getElementById('packages-panel-view').style.display = 'flex';
            document.getElementById('utilities-panel-view').style.display = 'none';

            const titles = {
                'strict_orphans': "Orphan Packages (Strict)",
                'optional_orphans': "Orphan Packages (Optional)",
                'explicit_gui': "Unused Explicit GUI Applications",
                'explicit_dev': "Unused Explicit Dev/Build Tools",
                'explicit_fonts_themes': "Unused Explicit Fonts & Themes",
                'explicit_cli_other': "Unused Explicit CLI & Others"
            };
            document.getElementById('current-cat-title').innerText = titles[cat] || "Packages";
            document.getElementById('search-input').value = '';
            
            renderPackageTable();
        }

        function renderPackageTable() {
            const tbody = document.getElementById('package-list-tbody');
            tbody.innerHTML = '';

            const searchVal = document.getElementById('search-input').value.toLowerCase();
            const sortBy = document.getElementById('sort-select').value;

            let pkgs = categoriesData[currentCategory] || [];

            if (searchVal) {
                pkgs = pkgs.filter(p => p.name.toLowerCase().includes(searchVal) || (p.description || '').toLowerCase().includes(searchVal));
            }

            if (sortBy === 'rec_size') {
                pkgs.sort((a, b) => b.recursive_size - a.recursive_size);
            } else if (sortBy === 'size') {
                pkgs.sort((a, b) => b.installed_size - a.installed_size);
            } else if (sortBy === 'name') {
                pkgs.sort((a, b) => a.name.localeCompare(b.name));
            } else if (sortBy === 'date') {
                pkgs.sort((a, b) => b.install_date - a.install_date);
            }

            if (pkgs.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;color:var(--text-muted);padding:3rem;">No packages found.</td></tr>`;
                return;
            }

            pkgs.forEach(pkg => {
                const tr = document.createElement('tr');
                const isChecked = selectedPackages[pkg.name] ? 'checked' : '';
                
                tr.innerHTML = `
                    <td><input type="checkbox" class="pkg-checkbox" ${isChecked} onchange="togglePackageSelection('${pkg.name}', this.checked)"></td>
                    <td><span class="pkg-name">${pkg.name}</span></td>
                    <td>${formatSize(pkg.installed_size)}</td>
                    <td style="color:var(--primary); font-weight:500;">${formatSize(pkg.recursive_size)}</td>
                    <td><div class="pkg-desc" title="${pkg.description}">${pkg.description || 'No description available'}</div></td>
                    <td style="text-align: right;"><button class="pkg-info-btn" onclick="showDetails('${currentCategory}', '${pkg.name}')">Inspect</button></td>
                `;
                tbody.appendChild(tr);
            });
        }

        function togglePackageSelection(name, isSelected) {
            if (isSelected) {
                selectedPackages[name] = true;
            } else {
                delete selectedPackages[name];
            }
            updateActionBar();
        }

        function toggleSelectAll(select) {
            const searchVal = document.getElementById('search-input').value.toLowerCase();
            let pkgs = categoriesData[currentCategory] || [];
            if (searchVal) {
                pkgs = pkgs.filter(p => p.name.toLowerCase().includes(searchVal) || p.description.toLowerCase().includes(searchVal));
            }

            pkgs.forEach(pkg => {
                if (select) {
                    selectedPackages[pkg.name] = true;
                } else {
                    delete selectedPackages[pkg.name];
                }
            });

            const checkboxes = document.querySelectorAll('.pkg-checkbox');
            checkboxes.forEach(cb => {
                const rowName = cb.closest('tr').querySelector('.pkg-name').innerText;
                cb.checked = selectedPackages[rowName] ? true : false;
            });

            updateActionBar();
        }

        function updateActionBar() {
            const bar = document.getElementById('floating-action-bar');
            const countSpan = document.getElementById('selected-count');
            const spaceSpan = document.getElementById('selected-space');

            const keys = Object.keys(selectedPackages);
            if (keys.length === 0) {
                bar.classList.remove('visible');
                return;
            }

            let visited = new Set();
            for (const cat in categoriesData) {
                categoriesData[cat].forEach(p => {
                    if (selectedPackages[p.name]) {
                        if (p.recursive_packages) {
                            p.recursive_packages.forEach(rp => visited.add(rp));
                        }
                        visited.add(p.name);
                    }
                });
            }

            let allPkgsMap = {};
            for (const cat in categoriesData) {
                categoriesData[cat].forEach(p => {
                    allPkgsMap[p.name] = p;
                });
            }

            let recursiveReclaimBytes = 0;
            visited.forEach(name => {
                if (allPkgsMap[name]) {
                    recursiveReclaimBytes += allPkgsMap[name].installed_size;
                }
            });

            countSpan.innerText = keys.length;
            spaceSpan.innerText = formatSize(recursiveReclaimBytes);
            bar.classList.add('visible');
        }

        function handleSearch() {
            renderPackageTable();
        }

        function handleSort() {
            renderPackageTable();
        }

        function showDetails(cat, name) {
            const pkg = categoriesData[cat].find(p => p.name === name);
            if (!pkg) return;

            document.getElementById('modal-pkg-name').innerText = `${pkg.name} (${pkg.version})`;
            
            let dateStr = 'N/A';
            if (pkg.install_date > 0) {
                dateStr = new Date(pkg.install_date * 1000).toLocaleString();
            }

            let dependsHtml = 'None';
            if (pkg.recursive_packages && pkg.recursive_packages.length > 1) {
                const subdeps = pkg.recursive_packages.filter(n => n !== pkg.name);
                dependsHtml = `<div class="dependency-list">${subdeps.map(n => `• ${n}`).join('<br>')}</div>`;
            }

            const body = document.getElementById('modal-pkg-body');
            body.innerHTML = `
                <div class="detail-row">
                    <span class="detail-lbl">Description</span>
                    <span class="detail-val">${pkg.description || 'No description'}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-lbl">Individual Size</span>
                    <span class="detail-val glow-blue" style="font-weight:600;">${formatSize(pkg.installed_size)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-lbl">Recursive Size</span>
                    <span class="detail-val glow-green" style="font-weight:600;">${formatSize(pkg.recursive_size)}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-lbl">Install Date</span>
                    <span class="detail-val">${dateStr}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-lbl">Project URL</span>
                    <span class="detail-val">${pkg.url ? `<a href="${pkg.url}" target="_blank" style="color:var(--primary);text-decoration:none;">${pkg.url}</a>` : 'N/A'}</span>
                </div>
                <div class="detail-row">
                    <span class="detail-lbl">Recursive Orphans</span>
                    <span class="detail-val">Will trigger removal of ${pkg.recursive_packages.length} packages total.<br>${dependsHtml}</span>
                </div>
            `;

            openModal('detail-modal-overlay');
        }

        function openModal(id) {
            document.getElementById(id).classList.add('active');
        }

        function closeModal(id) {
            document.getElementById(id).classList.remove('active');
        }

        function openCleanupReview() {
            const keys = Object.keys(selectedPackages);
            const container = document.getElementById('cleanup-review-stats');
            
            let visited = new Set();
            let allPkgsMap = {};
            for (const cat in categoriesData) {
                categoriesData[cat].forEach(p => {
                    allPkgsMap[p.name] = p;
                    if (selectedPackages[p.name]) {
                        if (p.recursive_packages) {
                            p.recursive_packages.forEach(rp => visited.add(rp));
                        }
                        visited.add(p.name);
                    }
                });
            }

            let reclaimBytes = 0;
            visited.forEach(name => {
                if (allPkgsMap[name]) reclaimBytes += allPkgsMap[name].installed_size;
            });

            container.innerHTML = `
                <div style="margin: 10px 0;">Selected explicitly: <span class="glow-blue">${keys.length} packages</span></div>
                <div style="margin: 10px 0;">Total packages to remove (with recursive dependencies): <span class="glow-blue">${visited.size} packages</span></div>
                <div style="margin: 10px 0; font-size:1.15rem;">Total disk space to free: <span class="glow-green" style="font-weight:700;">${formatSize(reclaimBytes)}</span></div>
            `;

            document.getElementById('cleanup-console').style.display = 'none';
            document.getElementById('cleanup-console').innerText = '';
            document.getElementById('btn-confirm-cleanup').style.display = 'block';
            document.getElementById('btn-cancel-cleanup').innerText = 'Cancel';

            openModal('review-modal-overlay');
        }

        async function executePurge() {
            const keys = Object.keys(selectedPackages);
            const consoleLog = document.getElementById('cleanup-console');
            consoleLog.style.display = 'block';
            consoleLog.innerText = 'Initializing package purge process...\nAuthenticating request (please check desktop authentication prompts if any)...\n';
            
            document.getElementById('btn-confirm-cleanup').style.display = 'none';
            document.getElementById('btn-cancel-cleanup').innerText = 'Close';

            try {
                const res = await fetch('/api/cleanup', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({packages: keys})
                });
                const data = await res.json();
                if (data.success) {
                    consoleLog.innerText += "Success: Packages removed successfully!\n";
                    selectedPackages = {};
                    updateActionBar();
                    await refreshData();
                    renderPackageTable();
                } else {
                    consoleLog.innerText += `Error: ${data.message || 'Operation failed'}\n`;
                }
            } catch (e) {
                consoleLog.innerText += `Fatal Connection Error: ${e.message}\n`;
            }
        }

        async function runCacheClean() {
            const mode = document.querySelector('input[name="cache-mode"]:checked').value;
            try {
                const res = await fetch('/api/cache-clean', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mode: mode})
                });
                const data = await res.json();
                alert(data.message);
                await refreshData();
            } catch (e) {
                alert("Failed to clean package cache: " + e.message);
            }
        }

        async function runJournalVacuum() {
            const mode = document.querySelector('input[name="journal-mode"]:checked').value;
            try {
                const res = await fetch('/api/journal-vacuum', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({mode: mode})
                });
                const data = await res.json();
                alert(data.message);
                await refreshData();
            } catch (e) {
                alert("Failed to vacuum journal logs: " + e.message);
            }
        }

        function formatSize(bytes) {
            if (bytes === 0) return '0 B';
            if (bytes < 1024) return bytes + ' B';
            const k = 1024;
            const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
    </script>
</body>
</html>
"""

# API handlers
engine_instance = None

def get_api_status():
    global engine_instance
    categories = engine_instance.load_system_state()
    
    cat_structure = {}
    for cat, pkgs in categories.items():
        cat_structure[cat] = []
        for p in pkgs:
            removals = engine_instance.get_recursive_removals(p.name)
            cat_structure[cat].append({
                'name': p.name,
                'version': p.version,
                'description': p.desc,
                'installed_size': p.isize,
                'recursive_size': sum(engine_instance.pkg_dict[name].isize for name in removals if name in engine_instance.pkg_dict),
                'recursive_packages': list(removals),
                'install_date': p.installdate,
                'url': p.url
            })
            
    return {
        'package_manager': engine_instance.get_package_manager_name(),
        'cache_size': engine_instance.backend.get_cache_size(),
        'journal_size': get_journal_size(),
        'categories': cat_structure
    }

class InraHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode("utf-8"))
        elif path == "/api/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                status_data = get_api_status()
                self.wfile.write(json.dumps(status_data).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else ""
        data = {}
        if body:
            try:
                data = json.loads(body)
            except Exception:
                pass
                
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        
        if path == "/api/cleanup":
            packages = data.get("packages", [])
            if not packages:
                self.wfile.write(json.dumps({"success": False, "message": "No packages selected."}).encode("utf-8"))
                return
                
            raw_cmd = engine_instance.backend.get_uninstall_cmd(packages)
            cmd = ["pkexec"] + raw_cmd if shutil.which("pkexec") else ["sudo"] + raw_cmd
            
            try:
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    self.wfile.write(json.dumps({"success": True, "message": "Packages uninstalled successfully."}).encode("utf-8"))
                else:
                    msg = res.stderr or res.stdout or f"Return code: {res.returncode}"
                    self.wfile.write(json.dumps({"success": False, "message": msg}).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "message": str(e)}).encode("utf-8"))
                
        elif path == "/api/cache-clean":
            mode = data.get("mode", "1")
            cmd = engine_instance.backend.clean_cache(mode)
            if not cmd:
                self.wfile.write(json.dumps({"success": False, "message": "Action not supported by package manager."}).encode("utf-8"))
                return
            run_cmd = ["pkexec"] + cmd[1:] if shutil.which("pkexec") else cmd
            try:
                res = subprocess.run(run_cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    self.wfile.write(json.dumps({"success": True, "message": "Cache cleaned successfully."}).encode("utf-8"))
                else:
                    self.wfile.write(json.dumps({"success": False, "message": res.stderr or "Error cleaning cache."}).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "message": str(e)}).encode("utf-8"))
                
        elif path == "/api/journal-vacuum":
            mode = str(data.get("mode", "1"))
            sub_cmd = []
            if mode == "1":
                sub_cmd = ["journalctl", "--vacuum-time=2d"]
            elif mode == "2":
                sub_cmd = ["journalctl", "--vacuum-time=7d"]
            elif mode == "3":
                sub_cmd = ["journalctl", "--vacuum-size=100M"]
            elif mode == "4":
                sub_cmd = ["journalctl", "--vacuum-size=500M"]
                
            cmd = ["pkexec"] + sub_cmd if shutil.which("pkexec") else ["sudo"] + sub_cmd
            try:
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode == 0:
                    self.wfile.write(json.dumps({"success": True, "message": "Journal logs vacuumed successfully."}).encode("utf-8"))
                else:
                    self.wfile.write(json.dumps({"success": False, "message": res.stderr or "Error cleaning journal logs."}).encode("utf-8"))
            except Exception as e:
                self.wfile.write(json.dumps({"success": False, "message": str(e)}).encode("utf-8"))

def start_gui_server(port):
    server = HTTPServer(('127.0.0.1', port), InraHTTPHandler)
    url = f"http://127.0.0.1:{port}"
    print(f"Starting local GUI Web server at {url} ...")
    threading.Thread(target=lambda: webbrowser.open(url)).start()
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

# =====================================================================
# MAIN ENTRYPOINT
# =====================================================================

def main():
    global NO_COLOR, engine_instance
    
    parser = argparse.ArgumentParser(description="INRA - Smart, Universal package purger and system cleaner.")
    parser.add_argument('-d', '--dry-run', action='store_true', help="Perform scan and report suggestions without entering interactive mode")
    parser.add_argument('--min-size', default="0", help="Filter packages in dry-run mode by recursive size (e.g. 10M, 50MB)")
    parser.add_argument('--json', action='store_true', help="Output scan result as JSON and exit")
    parser.add_argument('--no-color', action='store_true', help="Disable color outputs")
    parser.add_argument('--ignore-file', help="Path to custom ignore config file (default: ~/.config/inra/ignore.conf)")
    parser.add_argument('--gui', action='store_true', help="Start beautiful local Web GUI browser application")
    parser.add_argument('-p', '--port', type=int, default=17890, help="Port to run local GUI server on (default: 17890)")
    parser.add_argument('--purge', nargs='+', help="Purge the specified packages and their recursive orphans")
    parser.add_argument('--clean-cache', choices=['1', '2'], help="Clean package cache (1=uninstalled only, 2=all)")
    parser.add_argument('--vacuum-journal', choices=['1', '2', '3', '4'], help="Vacuum systemd journal (1=2d, 2=7d, 3=100M, 4=500M)")
    
    args = parser.parse_args()
    
    if args.no_color or os.environ.get('NO_COLOR'):
        NO_COLOR = True
        
    ignore_file_path = args.ignore_file
    if not ignore_file_path:
        home_config = os.path.expanduser('~/.config')
        ignore_dir = os.path.join(home_config, 'inra')
        ignore_file_path = os.path.join(ignore_dir, 'ignore.conf')
        
        if not os.path.exists(ignore_dir):
            try:
                os.makedirs(ignore_dir)
                with open(ignore_file_path, 'w') as f:
                    f.write("# INRA Ignore List\n")
                    f.write("# Put package names here (one per line) that you want to exclude from cleanup recommendations.\n")
                    f.write("# Lines starting with '#' are comments.\n\n")
                    f.write("# Examples:\n")
                    f.write("# neovim\n")
                    f.write("# rsync\n")
            except Exception:
                pass
                
    try:
        engine_instance = InraEngine(ignore_file_path)
    except PackageManagerError as e:
        print(color_text(f"Fatal Error: {e}", RED))
        sys.exit(1)
        
    if args.purge:
        engine_instance.load_system_state()
        raw_cmd = engine_instance.backend.get_uninstall_cmd(args.purge)
        print(f"Executing uninstall command: {' '.join(raw_cmd)}")
        res = subprocess.run(raw_cmd)
        sys.exit(res.returncode)

    if args.clean_cache:
        cmd = engine_instance.backend.clean_cache(args.clean_cache)
        if not cmd:
            print("Action not supported by package manager.")
            sys.exit(1)
        print(f"Executing cache clean command: {' '.join(cmd)}")
        res = subprocess.run(cmd)
        sys.exit(res.returncode)

    if args.vacuum_journal:
        mode = args.vacuum_journal
        sub_cmd = []
        if mode == "1":
            sub_cmd = ["journalctl", "--vacuum-time=2d"]
        elif mode == "2":
            sub_cmd = ["journalctl", "--vacuum-time=7d"]
        elif mode == "3":
            sub_cmd = ["journalctl", "--vacuum-size=100M"]
        elif mode == "4":
            sub_cmd = ["journalctl", "--vacuum-size=500M"]
        print(f"Executing journal vacuum command: {' '.join(sub_cmd)}")
        res = subprocess.run(sub_cmd)
        sys.exit(res.returncode)

    if args.gui:
        print("Scanning system packages and computing critical dependency trees...")
        engine_instance.load_system_state()
        start_gui_server(args.port)
        return

    if args.json:
        categories = engine_instance.load_system_state()
        run_json_output(categories, engine_instance)
        return
        
    if args.dry_run:
        print("Scanning system packages and computing critical dependency trees...")
        categories = engine_instance.load_system_state()
        try:
            min_size_bytes = parse_size(args.min_size)
        except ValueError as e:
            print(f"Error parsing size: {e}")
            sys.exit(1)
        run_dry_run_report(categories, min_size_bytes, engine_instance)
        return
        
    print("Scanning system packages and computing critical dependency trees...")
    categories = engine_instance.load_system_state()
    interactive_loop(categories, engine_instance)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting. Goodbye!")
        sys.exit(0)
