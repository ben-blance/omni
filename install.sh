#!/usr/bin/env bash
# OMNI installer — development / early-access path.
#
# Real one-line distribution (apt, or curl ... | sh against a release
# binary) isn't live yet. Until then this installs the CLI from source via
# pip, which is the right path both for local development and for early
# testers who clone the repo directly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Older pip/setuptools combos can't do PEP 660 editable installs and fail
# with "missing the 'build_editable' hook" — even pip's own isolated build
# env doesn't reliably dodge this on older pip. --no-build-isolation avoids
# it by reusing the setuptools/packaging installed here, so make sure
# those are new enough first.
if ! python3 -c "
import sys
try:
    import setuptools
    from packaging.version import Version
    sys.exit(0 if Version(setuptools.__version__) >= Version('68') else 1)
except Exception:
    sys.exit(1)
"; then
    echo "[omni] upgrading local setuptools/packaging (needed for editable installs) ..."
    if python3 -c "import torch" 2>/dev/null; then
        # Stay under torch's own setuptools<82 pin so we don't break it.
        pip install --user "setuptools>=68,<82" "packaging>=23"
    else
        pip install --user "setuptools>=68" "packaging>=23"
    fi
fi

pip install --user --no-build-isolation -e "$SCRIPT_DIR"

echo ""
echo "OMNI CLI installed. Try:  omni version"
echo ""
echo "No model is installed yet - omni needs a model generation before it"
echo "can compress or decompress anything:"
echo ""
echo "  omni model update"
