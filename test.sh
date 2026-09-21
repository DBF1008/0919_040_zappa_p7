#!/usr/bin/env bash
#
# Zappa unit test runner - manual testing entry point.
#
# Usage:
#   ./test.sh                Run every unit-test module, one by one.
#   ./test.sh <module ...>   Run only the given module(s), e.g.:
#                            ./test.sh tests/tests.py tests/test_refactor.py
#   ./test.sh list           List all runnable unit-test modules.
#   ./test.sh sanity         Syntax check + lightweight refactoring checks
#                            (no AWS credentials required).
#
# Each module is invoked in a separate interpreter invocation so that a
# failure in one module does not hide results from the others. The runner
# prefers nosetests (used by upstream Zappa) and falls back to the stdlib
# unittest runner when nose is not installed.
set -u

cd "$(dirname "$0")"

ALL_TEST_MODULES=(
    tests/tests.py
    tests/tests_async.py
    tests/tests_async_old.py
    tests/tests_docs.py
    tests/tests_middleware.py
    tests/tests_placebo.py
    tests/test_handler.py
    tests/test_refactor.py
)

color() { # $1=color $2=text
    printf "\033[%sm%s\033[0m\n" "$1" "$2"
}

if command -v python3 >/dev/null 2>&1; then
    PY=python3
elif command -v python >/dev/null 2>&1; then
    PY=python
else
    echo "Python interpreter not found." >&2
    exit 1
fi

if "$PY" -c 'import nose' 2>/dev/null; then
    RUNNER="nose"
else
    RUNNER="unittest"
fi

# Zappa itself only supports Python 3.6-3.8 (enforced in zappa/__init__.py).
# Warn up front so a failing import is not mistaken for a test failure.
if ! "$PY" -c 'import sys; assert sys.version_info[:2] in [(3, 6), (3, 7), (3, 8)])' 2>/dev/null; then
    color "1;33" "WARNING: this Zappa version only supports Python 3.6/3.7/3.8; $("$PY" --version) is running."
    color "1;33" "Tests importing the zappa package will fail in this interpreter. Use a 3.6-3.8 environment for the full manual run."
fi

run_module() {
    local module="$1"
    color "1;36" "==== Running ${module} (${RUNNER}) ===="
    if [ "$RUNNER" = "nose" ]; then
        "$PY" -m nose "$module"
    else
        # unittest wants dotted module paths without the .py suffix
        local dotted
        dotted="$("$PY" -c "import os,sys; print(os.path.splitext(sys.argv[1])[0].replace(os.sep, '.'))" "$module")"
        "$PY" -m unittest -v "$dotted"
    fi
}

case "${1:-all}" in
    list)
        printf '%s\n' "${ALL_TEST_MODULES[@]}"
        exit 0
        ;;
    sanity)
        color "1;36" "==== Byte-compiling all sources ===="
        "$PY" -m py_compile zappa/*.py tests/test_refactor.py || exit 1
        color "1;36" "==== Config module smoke test ===="
        # Loaded by file path so this works even on Python versions gated out
        # by zappa/__init__.py (the gate itself is unrelated to this change).
        ZAPPA_DISABLE_REGION_DISCOVERY=1 "$PY" - <<'PYTHON'
import importlib.util
spec = importlib.util.spec_from_file_location(
    'zappa_config_smoke', 'zappa/config.py')
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)
config.refresh_config()
assert 'us-east-1' in config.get_lambda_regions()
assert 'us-east-1' in config.get_api_gateway_regions()
assert '.git/*' in config.get_zip_excludes()
print('config defaults OK')
PYTHON
        color "1;36" "==== Running refactoring unit tests only ===="
        if "$PY" -c 'import sys; assert sys.version_info[:2] in [(3, 6), (3, 7), (3, 8)]' 2>/dev/null; then
            run_module tests/test_refactor.py
            exit $?
        fi
        color "1;33" "Skipped test_refactor.py: needs Python 3.6/3.7/3.8 (compile + config smoke already passed)."
        exit 0
        ;;
    all)
        modules=("${ALL_TEST_MODULES[@]}")
        ;;
    *)
        modules=("$@")
        ;;
esac

failed=()
passed=()
for module in "${modules[@]}"; do
    if [ ! -f "$module" ]; then
        color "1;31" "!! Module not found: ${module}"
        failed+=("$module (missing)")
        continue
    fi
    if run_module "$module"; then
        passed+=("$module")
    else
        failed+=("$module")
    fi
done

echo
color "1;32" "Passed: ${#passed[@]} module(s)"
for module in "${passed[@]}"; do echo "  PASS  $module"; done
if [ "${#failed[@]}" -gt 0 ]; then
    color "1;31" "Failed: ${#failed[@]} module(s)"
    for module in "${failed[@]}"; do echo "  FAIL  $module"; done
    exit 1
fi
