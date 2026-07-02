#!/usr/bin/env bash
# Inra Universal Packaging Script
# Generates .deb, .rpm, .appimage, and .tar.gz packages.

set -e

VERSION="1.0.0"
if [ -n "$1" ]; then
    VERSION="$1"
fi

echo "Packaging Inra v$VERSION..."

# 0. Compile C++ Qt6 GUI
echo "Compiling C++ Qt6 GUI..."
mkdir -p gui/build
cd gui/build
cmake ..
make -j$(nproc)
cd ../..

# Clean old builds
rm -rf dist build
mkdir -p dist

# 1. Build .tar.gz (Universal Source Package)
echo "Generating .tar.gz archive..."
mkdir -p build/inra-${VERSION}
cp inra.py build/inra-${VERSION}/
cp -P inra build/inra-${VERSION}/
cp gui/build/inra-gui build/inra-${VERSION}/
cp README.md build/inra-${VERSION}/
cp LICENSE build/inra-${VERSION}/
cp inra.desktop build/inra-${VERSION}/
cp inra.jpg build/inra-${VERSION}/
tar -czf dist/inra-${VERSION}.tar.gz -C build inra-${VERSION}
echo "Created: dist/inra-${VERSION}.tar.gz"

# 2. Build .deb (Debian/Ubuntu Package)
echo "Generating .deb package..."
DEB_DIR="build/inra_deb"
mkdir -p ${DEB_DIR}/DEBIAN
mkdir -p ${DEB_DIR}/usr/bin
mkdir -p ${DEB_DIR}/usr/share/applications
mkdir -p ${DEB_DIR}/usr/share/pixmaps

ARCH=$(dpkg --print-architecture 2>/dev/null || echo "amd64")

cat <<EOF > ${DEB_DIR}/DEBIAN/control
Package: inra
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: ${ARCH}
Maintainer: Dacraezy1 <https://github.com/Dacraezy1>
Description: Smart, Universal package purger and system cleaner.
 Inra identifies and purges unused packages, cleans cache, and vacuums systemd logs.
 Supports Arch Linux, Debian/Ubuntu, and Fedora/RHEL with interactive TUI and responsive Web GUI modes.
EOF

cp inra.py ${DEB_DIR}/usr/bin/inra
chmod +x ${DEB_DIR}/usr/bin/inra
cp gui/build/inra-gui ${DEB_DIR}/usr/bin/inra-gui
chmod +x ${DEB_DIR}/usr/bin/inra-gui
cp inra.desktop ${DEB_DIR}/usr/share/applications/
cp inra.jpg ${DEB_DIR}/usr/share/pixmaps/inra.jpg
if command -v convert &> /dev/null; then
    convert inra.jpg ${DEB_DIR}/usr/share/pixmaps/inra.png
else
    cp inra.jpg ${DEB_DIR}/usr/share/pixmaps/inra.png
fi

# Build debian package
dpkg-deb --build ${DEB_DIR} dist/inra-${VERSION}_${ARCH}.deb
echo "Created: dist/inra-${VERSION}_${ARCH}.deb"

# 3. Build .rpm (Fedora/RHEL Package via alien if available)
if command -v alien &> /dev/null; then
    echo "Generating .rpm package via alien..."
    alien --to-rpm dist/inra-${VERSION}_${ARCH}.deb
    mv inra-*.rpm dist/inra-${VERSION}.rpm
    echo "Created: dist/inra-${VERSION}.rpm"
else
    echo "Warning: 'alien' command not found. Skipping RPM generation."
    echo "Please install 'alien' and 'rpm' packages to build RPMs."
fi

# 4. Build .appimage (Universal AppImage)
echo "Generating .appimage package..."
APPDIR="build/Inra.AppDir"
mkdir -p ${APPDIR}/usr/bin
mkdir -p ${APPDIR}/usr/share/applications
mkdir -p ${APPDIR}/usr/share/pixmaps

# Copy files
cp inra.py ${APPDIR}/usr/bin/inra
chmod +x ${APPDIR}/usr/bin/inra
cp gui/build/inra-gui ${APPDIR}/usr/bin/inra-gui
chmod +x ${APPDIR}/usr/bin/inra-gui
cp inra.desktop ${APPDIR}/
cp inra.jpg ${APPDIR}/
if command -v convert &> /dev/null; then
    convert inra.jpg ${APPDIR}/inra.png
else
    cp inra.jpg ${APPDIR}/inra.png
fi

# Create AppRun launcher
cat <<EOF > ${APPDIR}/AppRun
#!/bin/sh
HERE="\$(dirname "\$(readlink -f "\${0}")")"
if [ -n "\$1" ] && [ "\$1" != "--gui" ]; then
    exec python3 "\${HERE}/usr/bin/inra" "\$@"
else
    exec "\${HERE}/usr/bin/inra-gui" "\$@"
fi
EOF
chmod +x ${APPDIR}/AppRun

# Download appimagetool if not present
if [ ! -f "appimagetool" ]; then
    echo "Downloading appimagetool..."
    curl -Lo appimagetool https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x appimagetool
fi

# Build AppImage
# Set ARCH=x86_64 as required by appimagetool
export ARCH=x86_64
./appimagetool --appimage-extract-and-run ${APPDIR} dist/inra-${VERSION}-universal.AppImage
echo "Created: dist/inra-${VERSION}-universal.AppImage"

echo "Packaging complete!"
ls -la dist/
