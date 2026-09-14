#!/usr/bin/env bash
# Build open-transcribe-assistant_<version>-<revision>_amd64.deb.
#
# The engine and the assistant are built from one clean source revision, in one run, with one
# recorded application version. The payload is root-owned, and nothing from the build machine's
# home directory, secrets, test results, or private configuration is copied into it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD="${OT_BUILD_DIR:-$ROOT/build/deb}"
DIST="$ROOT/dist"
REVISION="${OT_PACKAGE_REVISION:-1}"
PACKAGE="open-transcribe-assistant"
PREFIX="/opt/$PACKAGE"

VERSION="$(cd "$ROOT" && python -c 'import tomllib,pathlib;print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
FULL_VERSION="${VERSION}-${REVISION}"
STAGE="$BUILD/$PACKAGE"

echo "==> Building $PACKAGE $FULL_VERSION (amd64)"
rm -rf "$BUILD"
mkdir -p "$STAGE/DEBIAN" \
         "$STAGE$PREFIX" \
         "$STAGE/usr/bin" \
         "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/scalable/apps" \
         "$STAGE/usr/share/metainfo" \
         "$STAGE/usr/share/doc/$PACKAGE"
mkdir -p "$DIST"

export OT_SOURCE_ROOT="$ROOT"
export PYTHONHASHSEED=0
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(cd "$ROOT" && git log -1 --pretty=%ct 2>/dev/null || date +%s)}"

echo "==> Freezing the engine"
python -m PyInstaller --noconfirm --clean \
  --distpath "$BUILD/pyinstaller" --workpath "$BUILD/work" \
  "$ROOT/packaging/pyinstaller/engine.spec"

echo "==> Freezing OpenTranscribe Setup"
python -m PyInstaller --noconfirm --clean \
  --distpath "$BUILD/pyinstaller" --workpath "$BUILD/work" \
  "$ROOT/packaging/pyinstaller/assistant.spec"

echo "==> Assembling the payload"
cp -a "$BUILD/pyinstaller/assistant/." "$STAGE$PREFIX/"
# The engine's own libraries are merged in beside the assistant's: one directory, two
# executables, and a single recorded version for both.
cp -a "$BUILD/pyinstaller/engine/." "$STAGE$PREFIX/"

# `direct_url.json` records the path a distribution was installed from, which on a build host is
# a home directory. It has no runtime purpose, so it is removed rather than shipped.
find "$STAGE$PREFIX" -name direct_url.json -type f -delete

mkdir -p "$STAGE$PREFIX/share"
cp "$ROOT/packaging/desktop/open-transcribe-cleanup.service" "$STAGE$PREFIX/share/"
cp "$ROOT/packaging/desktop/open-transcribe-cleanup.timer" "$STAGE$PREFIX/share/"
cp "$ROOT/packaging/desktop/open-transcribe-assistant.svg" "$STAGE$PREFIX/share/"

install -m 0755 "$ROOT/packaging/debian/launcher" "$STAGE/usr/bin/$PACKAGE"
install -m 0644 "$ROOT/packaging/desktop/open-transcribe-assistant.desktop" \
  "$STAGE/usr/share/applications/$PACKAGE.desktop"
install -m 0644 "$ROOT/packaging/desktop/open-transcribe-assistant.svg" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps/$PACKAGE.svg"
sed -e "s/@VERSION@/$VERSION/" \
    -e "s/@RELEASE_DATE@/$(date -u -d "@$SOURCE_DATE_EPOCH" +%Y-%m-%d)/" \
  "$ROOT/packaging/desktop/io.github.fbossiere.OpenTranscribeSetup.metainfo.xml" \
  > "$STAGE/usr/share/metainfo/io.github.fbossiere.OpenTranscribeSetup.metainfo.xml"
chmod 0644 "$STAGE/usr/share/metainfo/io.github.fbossiere.OpenTranscribeSetup.metainfo.xml"

install -m 0644 "$ROOT/LICENSE" "$STAGE/usr/share/doc/$PACKAGE/LICENSE"
install -m 0644 "$ROOT/packaging/debian/copyright" "$STAGE/usr/share/doc/$PACKAGE/copyright"
install -m 0644 "$ROOT/docs/desktop.md" "$STAGE/usr/share/doc/$PACKAGE/README.md"
python "$ROOT/scripts/generate_notices.py" \
  --output "$STAGE/usr/share/doc/$PACKAGE/THIRD-PARTY-NOTICES"

echo "==> Deriving shared-library dependencies from the produced binaries"
SHLIB_DEPENDS="$(python "$ROOT/scripts/derive_deb_depends.py" "$STAGE$PREFIX")"
INSTALLED_SIZE="$(du -sk "$STAGE" | cut -f1)"

sed -e "s/@VERSION@/$FULL_VERSION/" \
    -e "s/@INSTALLED_SIZE@/$INSTALLED_SIZE/" \
    -e "s|@SHLIB_DEPENDS@|$SHLIB_DEPENDS|" \
  "$ROOT/packaging/debian/control.in" > "$STAGE/DEBIAN/control"
install -m 0755 "$ROOT/packaging/debian/postinst" "$STAGE/DEBIAN/postinst"
install -m 0755 "$ROOT/packaging/debian/prerm" "$STAGE/DEBIAN/prerm"
install -m 0755 "$ROOT/packaging/debian/postrm" "$STAGE/DEBIAN/postrm"

echo "==> Refusing build-machine leftovers"
python "$ROOT/scripts/check_deb_payload.py" "$STAGE"

echo "==> Packing"
ARCHIVE="$DIST/${PACKAGE}_${FULL_VERSION}_amd64.deb"
# --root-owner-group keeps the build user out of the archive metadata entirely.
dpkg-deb --root-owner-group --build "$STAGE" "$ARCHIVE" >/dev/null
sha256sum "$ARCHIVE" | tee "$ARCHIVE.sha256"
echo "==> Built $ARCHIVE"
