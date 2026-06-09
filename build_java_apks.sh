#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# build_java_apks.sh — собирает APK для http2socks и SuperPuperProxy (Java)
# Запускать из WSL: bash build_java_apks.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
GRADLE_VERSION="7.6.1"
GRADLE_ZIP="/tmp/gradle-${GRADLE_VERSION}-bin.zip"
GRADLE_DIR="/tmp/gradle-${GRADLE_VERSION}"
GRADLE="$GRADLE_DIR/bin/gradle"

# Скачать Gradle если ещё нет
if [ ! -f "$GRADLE" ]; then
    echo "⬇  Downloading Gradle $GRADLE_VERSION..."
    wget -q "https://services.gradle.org/distributions/gradle-${GRADLE_VERSION}-bin.zip" \
         -O "$GRADLE_ZIP"
    unzip -q "$GRADLE_ZIP" -d /tmp
    echo "✅ Gradle ready"
fi

# Нужен JAVA_HOME
if [ -z "$JAVA_HOME" ]; then
    export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which javac))))
    echo "ℹ  JAVA_HOME=$JAVA_HOME"
fi

build() {
    local name=$1
    local dir="$SCRIPT_DIR/$2"
    echo ""
    echo "════════════════════════════════════════"
    echo "  Building $name"
    echo "════════════════════════════════════════"
    cd "$dir"
    "$GRADLE" assembleDebug --no-daemon
    APK=$(find "$dir/app/build/outputs/apk/debug" -name "*.apk" | head -1)
    DEST="$dir/$(basename "$APK" | sed 's/-debug//')"
    cp "$APK" "$DEST"
    echo "✅ APK: $DEST"
}

build "http2socks (Java)"     "http2socks_java"
build "SuperPuperProxy (Java)" "superpuperproxy_java"

echo ""
echo "════════════════════════════════════════"
echo "  ВСЁ ГОТОВО"
echo "  APK файлы:"
ls -lh "$SCRIPT_DIR/http2socks_java"/*.apk 2>/dev/null || true
ls -lh "$SCRIPT_DIR/superpuperproxy_java"/*.apk 2>/dev/null || true
echo "════════════════════════════════════════"
