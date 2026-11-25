#!/bin/bash
# Set up a Mac to work on this project: what git doesn't hold, fetched or made. Safe to run again: it
# only does what's missing. Python is the project's own, through uv (brew install uv): the version in
# .python-version, uv's copy of it (not Homebrew's), with the tools' packages in .venv.
#
#   tools/setup.sh          the Python tools' environment (.venv) and the card fonts (assets/fonts/)
#   tools/setup.sh --ai     also the Scene Builder's AI ("find automatically": sky, water, where windows
#                           can be): its own environment (tools/themegen/work/aienv: PyTorch and
#                           transformers, about 1 GB) and the segmentation model (about 100 MB, Hugging Face)
#
# Then it says which of the other tools are here: the C compiler and swiftc (the Xcode command-line
# tools: the previewer), Apple's `container` (building the base system, tools/build/build.sh) and the
# GitHub CLI `gh` (publishing apps to the catalog, tools/apps/publish.py).
#
# The fonts are all under the SIL Open Font License, from Google Fonts' repository: Cormorant Garamond
# (the parchment and black cards, made into lining figures by tools/themegen/make_lining_font.py),
# Arvo Bold (the wood cards), Barlow Condensed SemiBold (the departure board). Photos are yours: the
# apps' kept scenes are in git, the photos they were made from aren't (assets/, git-ignored).
set -e
cd "$(dirname "$0")/.."
REPO=$(pwd)
AI=0; [ "$1" = "--ai" ] && AI=1
step() { printf '\n== %s\n' "$1"; }

step "Python (uv: the project's own, .python-version)"
command -v uv >/dev/null || { echo "no uv: install it (brew install uv, or: curl -LsSf https://astral.sh/uv/install.sh | sh), then run this again"; exit 1; }
PY=$(cat .python-version)
export UV_PYTHON_PREFERENCE=only-managed      # (uv's own Python, not Homebrew's: an upgrade there can't break these)
unset VIRTUAL_ENV CONDA_PREFIX                # (a virtualenv active in this terminal, another project's: not this one's)
uv python install "$PY" >/dev/null && echo "ok: Python $PY ($(uv python find "$PY"))"
# venv DIR: a virtualenv on that Python, made by uv; one that isn't (an older one, on Homebrew's Python), made afresh
venv() {
	if [ -f "$1/pyvenv.cfg" ] && grep -q "^uv = " "$1/pyvenv.cfg" && grep -q "^version_info = $PY" "$1/pyvenv.cfg"; then return; fi
	[ -d "$1" ] && echo "$1: not uv's Python $PY: made afresh"
	rm -rf "$1"; uv venv -q --python "$PY" "$1"
}

step "Python tools (.venv)"
venv .venv
uv sync -q                                    # (pyproject.toml's packages, at uv.lock's versions)
echo "ok: $(.venv/bin/python --version), $(uv pip list --python .venv/bin/python 2>/dev/null | grep -ciE '^(pillow|pyserial|fonttools|pyflakes) ') packages"

step "Card fonts (assets/fonts/)"
FONTS=assets/fonts; mkdir -p "$FONTS"
GF=https://github.com/google/fonts/raw/main/ofl
fetch() {   # fetch URL FILE: only when it isn't here; checked to be a font (or the licence) before it's kept
	[ -s "$FONTS/$2" ] && { echo "have $2"; return; }
	local tmp; tmp=$(mktemp)
	curl -sSfL -o "$tmp" "$1" || { rm -f "$tmp"; echo "couldn't fetch $2 ($1)"; return 1; }
	case "$2" in
		*.ttf) file "$tmp" | grep -q "TrueType" || { rm -f "$tmp"; echo "$2: not a font"; return 1; } ;;
	esac
	mv "$tmp" "$FONTS/$2"; echo "got $2"
}
fetch "$GF/cormorantgaramond/CormorantGaramond%5Bwght%5D.ttf" "CormorantGaramond[wght].ttf"
fetch "$GF/arvo/Arvo-Bold.ttf" "Arvo-Bold.ttf"
fetch "$GF/barlowcondensed/BarlowCondensed-SemiBold.ttf" "BarlowCondensed-SemiBold.ttf"
fetch "$GF/cormorantgaramond/OFL.txt" "OFL.txt"
if [ -s "$FONTS/CormorantGaramond-SemiBold-Lining.ttf" ]; then echo "have CormorantGaramond-SemiBold-Lining.ttf"
else .venv/bin/python tools/themegen/make_lining_font.py; fi

if [ $AI = 1 ]; then
	step "Scene Builder AI (tools/themegen/work/aienv)"
	ENV=tools/themegen/work/aienv
	venv $ENV
	uv pip install -q --python $ENV/bin/python torch torchvision transformers pillow
	# the model, fetched now (not the first time a photo is dropped): segment a small made-up picture
	tmp=$(mktemp -d)
	$ENV/bin/python -c "from PIL import Image; Image.new('RGB', (64, 48), (120, 160, 220)).save('$tmp/t.png')"
	$ENV/bin/python tools/themegen/segment.py "$tmp/t.png" "$tmp/s.png" "$tmp/s.json" && echo "ok: the segmentation model runs"
	rm -rf "$tmp"
fi

step "Other tools"
have() { command -v "$1" >/dev/null && echo "ok: $1 ($2)" || echo "missing: $1 ($2): $3"; }
have cc "the drawing library, for the previewer and the check" "xcode-select --install"
have swiftc "the App Preview window" "xcode-select --install"
have container "building the base system" "Apple's container: github.com/apple/container"
have gh "publishing apps to the catalog" "brew install gh; gh auth login"
if [ $AI = 0 ]; then
	A=tools/themegen/work/aienv/pyvenv.cfg
	if [ ! -f $A ]; then echo "not set up: the Scene Builder's AI (tools/setup.sh --ai; without it, finding sky, water and windows goes by colour)"
	elif grep -q "^uv = " $A && grep -q "^version_info = $PY" $A; then echo "ok: the Scene Builder's AI"
	else echo "the Scene Builder's AI is on an older Python (not uv's $PY): tools/setup.sh --ai makes it afresh"; fi
fi
printf '\nReady: tools/preview/preview.py APP (the previewer), tools/test/check.py (the check)\n'
