#!/usr/bin/env bash
# Baut ein VP-Image mit einem bestimmten Pydrofoil-Plugin, abgeleitet vom
# Release-Image. VP-Quellen und Buildtyp bleiben identisch, nur das Plugin
# wird getauscht und die CFFI-Glue/der VP dagegen neu gebaut. Genau das
# braucht der Vergleich A (ohne Poison) vs. B (mit Poison) auf Pfad 2
# (thesis/messplan.md §3).
#
#   ./tools/bench/build_vp_image.sh <plugin-dir | plugin.tar.bz2> <tag> [--expect poison|plain]
#
# Beispiele:
#   ./tools/bench/build_vp_image.sh ~/nopoison.tar.bz2 release-nopoison --expect plain
#   ./tools/bench/build_vp_image.sh old-pypy-pydrofoil-scripting-experimental \
#       release-poison-old --expect poison                    # Variante D
#
# Das Plugin-Verzeichnis ist das, was sonst unter
# pypy-pydrofoil-scripting-experimental/ liegt (bin/libpypy3.11-c.so, include/,
# lib/). Ein Tarball darf genau ein solches Verzeichnis enthalten.
#
# Wichtig: Fuer A/B sollten beide Plugins aus DEMSELBEN Build stammen. Die
# Plugins tragen keinen Modell-Versionsstring (anders als die Standalone-
# Binaries), die Herkunft ist im Nachhinein nicht pruefbar.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_IMAGE="${BASE_IMAGE:-vcml-pydrofoil:release-poison}"

usage() { echo "usage: $0 <plugin-dir|plugin.tar.bz2> <tag> [--expect poison|plain]" >&2; exit 1; }
[[ $# -ge 2 ]] || usage
SRC=$1
TAG=$2
EXPECT=""
if [[ $# -ge 3 ]]; then
	[[ $3 == --expect && $# -eq 4 ]] || usage
	EXPECT=$4
	[[ $EXPECT == poison || $EXPECT == plain ]] || usage
fi

podman image exists "$BASE_IMAGE" || {
	echo "Basis-Image $BASE_IMAGE fehlt. Bauen mit:" >&2
	echo "  podman build --build-arg CMAKE_BUILD_TYPE=Release -t $BASE_IMAGE $REPO" >&2
	exit 1
}

CTX="$(mktemp -d "${TMPDIR:-/tmp}/vp-image.XXXXXX")"
trap 'rm -rf "$CTX"' EXIT

if [[ -d $SRC ]]; then
	cp -a "$SRC" "$CTX/plugin"
elif [[ -f $SRC ]]; then
	mkdir "$CTX/x"
	tar -xjf "$SRC" -C "$CTX/x"
	mapfile -t tops < <(find "$CTX/x" -mindepth 1 -maxdepth 1)
	[[ ${#tops[@]} -eq 1 && -d ${tops[0]} ]] || { echo "Tarball muss genau ein Verzeichnis enthalten" >&2; exit 1; }
	mv "${tops[0]}" "$CTX/plugin"
else
	echo "nicht gefunden: $SRC" >&2
	exit 1
fi

SO="$CTX/plugin/bin/libpypy3.11-c.so"
[[ -f $SO ]] || { echo "kein Plugin: $SO fehlt" >&2; exit 1; }

# Poison-Unterstuetzung am Symbol erkennen (Sail-Funktion aus
# model/riscv_shadow_mem.sail), bevor eine Stunde Messung am falschen Plugin
# haengt.
# Prozess-Substitution statt Pipe: grep -q beendet sich beim ersten Treffer,
# strings bekaeme SIGPIPE und pipefail wertete das als 'kein Treffer'.
if grep -q 'zshadow_fill' < <(strings "$SO"); then HAS=poison; else HAS=plain; fi
echo "Plugin: $(sha256sum "$SO" | cut -c1-16)...  Poison-Symbole: $HAS"
if [[ -n $EXPECT && $EXPECT != "$HAS" ]]; then
	echo "FEHLER: erwartet --expect $EXPECT, Plugin ist $HAS" >&2
	exit 1
fi

cat >"$CTX/Containerfile" <<EOF
FROM $BASE_IMAGE
RUN rm -rf /vcml-pydrofoil/pypy-pydrofoil-scripting-experimental
COPY plugin /vcml-pydrofoil/pypy-pydrofoil-scripting-experimental
WORKDIR /vcml-pydrofoil
# CMAKE_BUILD_TYPE (Release) kommt als ENV aus dem Basis-Image.
RUN ./build_sim.sh && chmod -R a+rX /vcml-pydrofoil
LABEL bench.plugin.sha256="$(sha256sum "$SO" | cut -d' ' -f1)" \\
      bench.plugin.poison="$HAS" \\
      bench.plugin.source="$(basename "$SRC")"
EOF

podman build -t "vcml-pydrofoil:$TAG" -f "$CTX/Containerfile" "$CTX"
echo
echo "Image: vcml-pydrofoil:$TAG ($HAS)"
