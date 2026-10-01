#!/usr/bin/env bash
# Build a headless-safe XFoil 6.99 from the Ubuntu/Debian source package.
#
# Why not `apt-get install xfoil`? The packaged binary keeps the upstream
# debug flags (-ffpe-trap=invalid,zero -finit-real=inf), so harmless FP events
# inside the viscous solver (and the PPAR menu when graphics are off) abort
# the process with SIGFPE. We rebuild with the same Debian patches but
# without FP trapping. Graphics stay compiled in and are switched off at run
# time with `PLOP / G`; no X display is ever opened.
#
# Usage: scripts/install_xfoil.sh [PREFIX]   (default PREFIX=/usr/local)
# Idempotent: exits early if $PREFIX/bin/xfoil already reports the
# aeroswarm build marker.
set -euo pipefail

PREFIX="${1:-/usr/local}"
DEST="$PREFIX/bin/xfoil"
MARKER="$PREFIX/share/aeroswarm/xfoil.built"
MIRROR="${UBUNTU_MIRROR:-http://archive.ubuntu.com/ubuntu}"
VER="6.99.dfsg+1"
DEBREV="3"

if [[ -x "$DEST" && -f "$MARKER" ]]; then
  echo "xfoil already installed at $DEST"
  exit 0
fi

need=()
command -v gfortran >/dev/null || need+=(gfortran)
[[ -f /usr/include/X11/Xlib.h ]] || need+=(libx11-dev)
command -v patch >/dev/null || need+=(patch)
command -v make >/dev/null || need+=(make)
if ((${#need[@]})); then
  SUDO=""; [[ $EUID -ne 0 ]] && SUDO="sudo"
  $SUDO apt-get update -qq || true
  $SUDO apt-get install -y -qq "${need[@]}"
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
curl -fsSLO "$MIRROR/pool/universe/x/xfoil/xfoil_${VER}.orig.tar.gz"
curl -fsSLO "$MIRROR/pool/universe/x/xfoil/xfoil_${VER}-${DEBREV}.debian.tar.xz"
tar xzf "xfoil_${VER}.orig.tar.gz"
tar xJf "xfoil_${VER}-${DEBREV}.debian.tar.xz"
cd Xfoil
while read -r p; do
  [[ -z "$p" || "$p" == \#* ]] && continue
  patch -p1 -s < "../debian/patches/$p"
done < ../debian/patches/series

# Drop the FP traps / inf initialisation, keep double precision.
sed -i "s/^CHK = .*/CHK = -O2 -fallow-argument-mismatch/" bin/Makefile
sed -i 's/-fbounds-check -finit-real=inf -ffpe-trap=invalid,zero //' plotlib/config.make

make -s -C orrs/bin -f Makefile_DP osgen >/dev/null
(cd orrs && bin/osgen osmaps_ns.lst >/dev/null)
make -s -C plotlib >/dev/null
make -s -C bin xfoil >/dev/null

SUDO=""; [[ $EUID -ne 0 && ! -w "$PREFIX" ]] && SUDO="sudo"
$SUDO install -D -m 755 bin/xfoil "$DEST"
$SUDO install -D -m 644 orrs/osmap.dat "$PREFIX/share/aeroswarm/osmap.dat"
echo "$VER-$DEBREV no-fpe-trap" | $SUDO tee "$MARKER" >/dev/null
echo "installed $DEST"
