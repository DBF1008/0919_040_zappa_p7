#! /bin/bash
#
# Zappa unit test runner.
#
# Runs every unit test script independently so that a failure in one script
# does not hide the results of the others.
#
# Usage:
#   ./test.sh                 Run all unit test scripts, one at a time.
#   ./test.sh all             Same as above (explicit).
#   ./test.sh list            List the available unit test scripts.
#   ./test.sh tests           Run only the main tests/tests.py script.
#   ./test.sh <script>        Run a single script, e.g. ./test.sh test_handler
#   ./test.sh tests.py:TestZappa.test_cli_sanity
#                             Run a single test (nose/unittest dotted path).
#   ./test.sh clean           Remove caches and bytecode.
#
# Test discovery: every tests/*.py file that defines a TestCase is a script.
# Add a new file under tests/ and it is picked up automatically.

set -u

cd "$(dirname "$0")"

TEST_DIR="tests"

# Scripts run individually, in a deterministic order.
TEST_SCRIPTS=(
    "tests_docs.py"
    "test_handler.py"
    "tests_middleware.py"
    "tests_placebo.py"
    "tests_async.py"
    "tests_async_old.py"
    "tests.py"
)

#
# Pick the best available test runner. Prefer pytest, fall back to nose and
# finally to the stdlib unittest module.
#
select_runner() {
    if python -c "import pytest" 2>/dev/null; then
        echo "pytest"
    elif python -c "import nose" 2>/dev/null; then
        echo "nose"
    else
        echo "unittest"
    fi
}

#
# Run a single test path (file or dotted nose-style path) with the runner.
#
run_target() {
    local target="$1"
    local runner
    runner="$(select_runner)"

    echo "=================================================================="
    echo "Running: ${target} (runner: ${runner})"
    echo "=================================================================="

    case "${runner}" in
        pytest)
            # Accept "tests.py:TestZappa.test_x" too and translate the ':'.
            if [[ "${target}" == *:* ]]; then
                local module_path="${target%%:*}"
                local rest="${target#*:}"
                python -m pytest -v "${TEST_DIR}/${module_path%.py}.py::${rest//./::}"
            elif [[ "${target}" == *.py ]]; then
                python -m pytest -v "${TEST_DIR}/${target}"
            else
                python -m pytest -v "${target}"
            fi
            ;;
        nose)
            if [[ "${target}" == *.py ]]; then
                python -m nose -v "${TEST_DIR}/${target}"
            else
                python -m nose -v "${target}"
            fi
            ;;
        unittest)
            echo "WARNING: pytest/nose not found; falling back to unittest."
            echo "         Install test requirements first:"
            echo "             pip install -r test_requirements.txt"
            if [[ "${target}" == *:* ]]; then
                # "tests.py:TestZappa.test_x" -> tests.tests.TestZappa.test_x
                local module_path="${target%%:*}"
                local rest="${target#*:}"
                python -m unittest -v "tests.${module_path%.py}.${rest}"
            elif [[ "${target}" == *.py ]]; then
                python -m unittest -v "tests.${target%.py}"
            else
                python -m unittest -v "${target}"
            fi
            ;;
    esac
}

#
# Run every test script independently and report a summary at the end.
#
run_all() {
    local failed=()
    local passed=()

    for script in "${TEST_SCRIPTS[@]}"; do
        if run_target "${script}"; then
            passed+=("${script}")
        else
            failed+=("${script}")
        fi
    done

    echo ""
    echo "=================================================================="
    echo "Test summary"
    echo "=================================================================="
    for script in "${passed[@]:-}"; do
        [[ -z "${script}" ]] && continue
        echo "  PASS  ${script}"
    done
    for script in "${failed[@]:-}"; do
        [[ -z "${script}" ]] && continue
        echo "  FAIL  ${script}"
    done
    echo "------------------------------------------------------------------"
    echo "${#passed[@]} passed, ${#failed[@]} failed (of ${#TEST_SCRIPTS[@]} scripts)"

    if [[ "${#failed[@]}" -gt 0 ]]; then
        return 1
    fi
}

#
# List the test scripts a developer can run manually.
#
list_scripts() {
    echo "Available unit test scripts:"
    for script in "${TEST_SCRIPTS[@]}"; do
        echo "  ${script}"
    done
    echo ""
    echo "Run a single script:  ./test.sh ${TEST_SCRIPTS[0]}"
    echo "Run a single test:    ./test.sh tests.py:TestZappa.test_cli_sanity"
}

case "${1:-all}" in
    all)
        run_all
        ;;
    list|ls)
        list_scripts
        ;;
    tests|tests.py)
        run_target "tests.py"
        ;;
    clean)
        find . -type d -name '__pycache__' -prune -exec rm -rf {} +
        find . -type f -name '*.pyc' -delete
        echo "Cleaned caches."
        ;;
    *)
        # Allow "./test.sh test_handler" as shorthand.
        target="$1"
        if [[ -f "${TEST_DIR}/${target}" ]]; then
            run_target "${target}"
        elif [[ -f "${TEST_DIR}/${target}.py" ]]; then
            run_target "${target}.py"
        else
            run_target "${target}"
        fi
        ;;
esac
