"""Exercise the RHEL dependency stage without touching the host's repositories."""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


DEPLOY = Path(__file__).resolve().parents[1] / "deploy-rhel.sh"


class RhelDependencyTests(unittest.TestCase):
    def run_dependency_stage(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            mock_bin = root / "bin"
            mock_bin.mkdir()
            release = root / "os-release"
            release.write_text('ID=rhel\nVERSION_ID="9.4"\n')
            log = root / "dnf.log"

            # Keep the real argument parsing and dependency stage, then stop
            # before building binaries or changing the user's installation.
            source = DEPLOY.read_text()
            self.assertIn("# ---------------------------------------------------------------- toolchain", source)
            self.assertIn("/etc/os-release", source)
            source = source.split("# ---------------------------------------------------------------- toolchain", 1)[0]
            source = source.replace("/etc/os-release", str(release))
            original_have = 'have() { command -v "$1" >/dev/null 2>&1; }'
            self.assertIn(original_have, source)
            absent = ["crb"]
            if mode not in ("registered", "registered-late-epel"):
                absent.append("subscription-manager")
            if mode == "rhui":
                absent.remove("crb")
            if mode == "installed":
                absent.append("sudo")
            if mode == "oldpython":
                absent.extend(("python3.13", "python3.12", "python3.11", "python3.10"))
            source = source.replace(
                original_have,
                f'have() {{ case "$1" in {"|".join(absent)}) return 1;; esac; command -v "$1" >/dev/null 2>&1; }}',
            )
            script = root / "deploy-rhel.sh"
            script.write_text(source)

            (mock_bin / "id").write_text('#!/bin/sh\n[ "$1" = -u ] && { echo "$MOCK_UID"; exit 0; }\nexit 1\n')
            (mock_bin / "rpm").write_text('#!/bin/sh\n[ "$MOCK_MODE" = installed ]\n')
            if mode == "oldpython":
                # A Python executable exists, but its version probe fails as
                # it would for the RHEL system Python 3.9.
                (mock_bin / "python3").write_text('#!/bin/sh\nexit 1\n')
            if mode in ("registered", "registered-late-epel"):
                (mock_bin / "subscription-manager").write_text(
                    '#!/bin/sh\nprintf "%s\\n" "$*" >> "$MOCK_SUBSCRIPTION_LOG"\n'
                    'touch "$MOCK_CODEREADY_STATE"\n'
                )
            if mode == "rhui":
                (mock_bin / "crb").write_text(
                    '#!/bin/sh\n[ "$*" = enable ] || exit 1\n'
                    'touch "$MOCK_RHUI_STATE"\n'
                )
            (mock_bin / "dnf").write_text("""#!/bin/sh
printf '%s\\n' "$*" >> "$MOCK_DNF_LOG"
case "$*" in
  '-q repolist --enabled')
    echo 'custom-rhel9 Custom mirror'
    [ ! -f "$MOCK_EPEL_STATE" ] || echo 'epel EPEL'
    [ ! -f "$MOCK_CODEREADY_STATE" ] || echo "codeready-builder-for-rhel-9-$(uname -m)-rpms CodeReady"
    exit 0 ;;
  '-y list python3.12'|'-y list python3.11'|'-y list python3.10') exit 1 ;;
  '-y install https://'*epel-release*)
    if [ "$MOCK_MODE" = missing ] ||
       { [ "$MOCK_MODE" = registered-late-epel ] && [ ! -f "$MOCK_CODEREADY_STATE" ]; }; then
      exit 1
    fi
    touch "$MOCK_EPEL_PACKAGE"; exit 0 ;;
  '-y install dnf-plugins-core')
    [ "$MOCK_MODE" != missing ] ;;
  'config-manager --set-enabled epel')
    [ -f "$MOCK_EPEL_PACKAGE" ] || exit 1
    touch "$MOCK_EPEL_STATE"; exit 0 ;;
  '-y install '*clang-devel*)
    [ "$MOCK_MODE" = available ] ||
      { [ "$MOCK_MODE" = epel ] && [ -f "$MOCK_EPEL_STATE" ]; } ||
      { [ "$MOCK_MODE" = registered ] && [ -f "$MOCK_CODEREADY_STATE" ]; } ||
      { [ "$MOCK_MODE" = registered-late-epel ] && [ -f "$MOCK_CODEREADY_STATE" ] && [ -f "$MOCK_EPEL_STATE" ]; } ||
      { [ "$MOCK_MODE" = rhui ] && [ -f "$MOCK_RHUI_STATE" ]; } ;;
esac
exit $?
""")
            names = ["id", "rpm", "dnf"]
            if mode in ("registered", "registered-late-epel"):
                names.append("subscription-manager")
            if mode == "rhui":
                names.append("crb")
            if mode == "oldpython":
                names.append("python3")
            for name in names:
                (mock_bin / name).chmod(0o755)

            env = os.environ.copy()
            env.update(
                PATH=f"{mock_bin}:{os.environ['PATH']}",
                HOME=str(root),
                MOCK_DNF_LOG=str(log),
                MOCK_EPEL_STATE=str(root / "epel-enabled"),
                MOCK_EPEL_PACKAGE=str(root / "epel-package"),
                MOCK_CODEREADY_STATE=str(root / "codeready-enabled"),
                MOCK_RHUI_STATE=str(root / "rhui-enabled"),
                MOCK_SUBSCRIPTION_LOG=str(root / "subscription.log"),
                MOCK_MODE=mode,
                MOCK_UID="1000" if mode == "installed" else "0",
            )
            result = subprocess.run(
                ["bash", str(script), "--server-only", "--skip-tests", "--prefix", str(root / "install")],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            subscription_log = root / "subscription.log"
            return (
                result,
                log.read_text().splitlines() if log.exists() else [],
                subscription_log.read_text().splitlines() if subscription_log.exists() else [],
                (root / "rhui-enabled").exists(),
            )

    def test_available_packages_do_not_require_subscription_or_epel(self):
        result, calls, subscription_calls, _ = self.run_dependency_stage("available")
        self.assertEqual(result.returncode, 0, f"{result.stderr}\n{calls}")
        self.assertEqual(sum("clang-devel" in call for call in calls), 1)
        self.assertFalse(any("epel-release" in call or "config-manager" in call for call in calls))
        self.assertEqual(subscription_calls, [])

    def test_preinstalled_packages_need_neither_sudo_nor_repositories(self):
        result, calls, subscription_calls, _ = self.run_dependency_stage("installed")
        self.assertEqual(result.returncode, 0, f"{result.stderr}\n{calls}")
        self.assertIn("build packages already installed", result.stdout)
        self.assertFalse(any(call.startswith("-y install") for call in calls))
        self.assertEqual(subscription_calls, [])

    def test_epel_can_supply_packages_without_subscription_manager(self):
        result, calls, subscription_calls, _ = self.run_dependency_stage("epel")
        self.assertEqual(result.returncode, 0, f"{result.stderr}\n{calls}")
        self.assertEqual(sum("clang-devel" in call for call in calls), 2)
        self.assertTrue(any("epel-release" in call for call in calls))
        self.assertEqual(subscription_calls, [])

    def test_registered_rhel_enables_codeready_only_after_install_fails(self):
        result, calls, subscription_calls, _ = self.run_dependency_stage("registered")
        self.assertEqual(result.returncode, 0, f"{result.stderr}\n{calls}")
        self.assertEqual(sum("clang-devel" in call for call in calls), 3)
        self.assertEqual(len(subscription_calls), 1)
        self.assertIn("repos --enable codeready-builder-for-rhel-9-", subscription_calls[0])

    def test_registered_rhel_retries_epel_after_codeready(self):
        result, calls, subscription_calls, _ = self.run_dependency_stage("registered-late-epel")
        self.assertEqual(result.returncode, 0, f"{result.stderr}\n{calls}")
        self.assertEqual(len(subscription_calls), 1)
        self.assertEqual(sum("epel-release" in call for call in calls), 2)

    def test_missing_packages_report_repository_options(self):
        result, calls, subscription_calls, _ = self.run_dependency_stage("missing")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sum("clang-devel" in call for call in calls), 3)
        self.assertIn("configure repositories", result.stderr)
        self.assertIn("register this RHEL host", result.stderr)
        self.assertIn("--skip-deps", result.stderr)
        self.assertEqual(subscription_calls, [])

    def test_old_system_python_is_requested_as_a_dependency(self):
        result, calls, _, _ = self.run_dependency_stage("oldpython")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(any("clang-devel" in call and "python3.11" in call for call in calls))
        self.assertIn("Python 3.11", result.stderr)

    def test_rhui_crb_helper_resolves_dependencies_without_subscription(self):
        result, calls, subscription_calls, rhui_enabled = self.run_dependency_stage("rhui")
        self.assertEqual(result.returncode, 0, f"{result.stderr}\n{calls}")
        self.assertTrue(rhui_enabled)
        self.assertEqual(sum("clang-devel" in call for call in calls), 3)
        self.assertEqual(subscription_calls, [])


if __name__ == "__main__":
    unittest.main()
