"""Isolated Z-12 release-transition checks; never contacts Azure or Docker."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SHA1, SHA2 = "1" * 40, "2" * 40


@unittest.skipIf(sys.platform == "win32", "Z-12 deployment scripts run on Linux; native Windows Bash temp paths are incompatible")
class DeploymentTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for file, content in {
            "compose.ghcr.yml": "services: {}\n",
            "runtime.env": "DUMMY=yes\n",
            "main.baseline": SHA1 + "\n",
            "image.env": self.tag(SHA1),
            "image.last-good.env": self.tag(SHA1),
            "images": "\n".join(
                f"ghcr.io/zaraherehehe/amrtrace-studio-{service}:sha-{sha}"
                for sha in (SHA1, SHA2) for service in ("api", "web")
            ) + "\n",
        }.items():
            (self.root / file).write_text(content)
        self.mock("git", '#!/bin/sh\nprintf "%s\\trefs/heads/main\\n" "$MOCK_MAIN_SHA"\n')
        self.mock("docker", '''#!/bin/bash
set -eu
case "$1" in
  pull) exit 0 ;;
  image) [[ "$2" == inspect ]] && grep -Fxq -- "${@: -1}" "$MOCK_IMAGES" ;;
  compose)
    tag="$(sed -n 's/^AMRTRACE_IMAGE_TAG=//p' "$MOCK_ROOT/image.env")"
    echo "up:$tag" >> "$MOCK_ROOT/deploy.log"
    exit 0 ;;
  *) exit 5 ;;
esac
''')
        self.mock("curl", '''#!/bin/bash
tag="$(sed -n 's/^AMRTRACE_IMAGE_TAG=//p' "$MOCK_ROOT/image.env")"
[[ "$tag" != "${MOCK_BAD_HEALTH:-none}" ]]
''')
        self.mock("sleep", "#!/bin/sh\nexit 0\n")
        self.env = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"],
                        MOCK_ROOT=str(self.root), MOCK_IMAGES=str(self.root / "images"),
                        MOCK_MAIN_SHA=SHA2)
        self.scripts = {}
        for name in ("z12_deploy_poll", "z12_rollback"):
            script = (ROOT / "scripts" / (name + ".sh")).read_text()
            script = script.replace("ROOT=/opt/amrtrace-studio", 'ROOT="$MOCK_ROOT"', 1)
            script = script.replace("/run/lock/amrtrace-z12-deploy.lock", str(self.root / "lock"))
            script = script.replace('if [[ ${EUID} -ne 0 ]]; then', 'if false; then', 1)
            path = self.root / (name + ".sh")
            path.write_text(script)
            self.scripts[name] = path

    @staticmethod
    def tag(sha):
        return f"AMRTRACE_IMAGE_TAG=sha-{sha}\n"

    def mock(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_script(self, name, *args, **env):
        return subprocess.run(["bash", str(self.scripts[name]), *args],
                              env={**self.env, **env}, text=True, capture_output=True, timeout=15)

    def read(self, name):
        return (self.root / name).read_text()

    def test_successful_upgrade_and_cross_version_rollback(self):
        upgrade = self.run_script("z12_deploy_poll")
        self.assertEqual(upgrade.returncode, 0, upgrade.stderr)
        self.assertEqual(self.read("image.env"), self.tag(SHA2))
        self.assertEqual(self.read("image.previous.env"), self.tag(SHA1))
        self.assertEqual(self.read("image.last-good.env"), self.tag(SHA2))
        check = self.run_script("z12_rollback", "--check")
        self.assertEqual(check.returncode, 0, check.stderr)
        rollback = self.run_script("z12_rollback", "--apply")
        self.assertEqual(rollback.returncode, 0, rollback.stderr)
        self.assertEqual(self.read("image.env"), self.tag(SHA1))
        self.assertEqual(self.read("image.last-good.env"), self.tag(SHA1))
        self.assertIn("ROLLBACK_REDEPLOY_VERIFIED=", rollback.stdout)
        self.assertNotEqual(self.run_script("z12_rollback", "--apply").returncode, 0)

    def test_failed_deploy_does_not_overwrite_previous(self):
        (self.root / "image.previous.env").write_text(self.tag(SHA1))
        failed = self.run_script("z12_deploy_poll", MOCK_BAD_HEALTH="sha-" + SHA2)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("ROLLBACK_SUCCESS", failed.stderr)
        self.assertEqual(self.read("image.env"), self.tag(SHA1))
        self.assertEqual(self.read("image.previous.env"), self.tag(SHA1))
        self.assertEqual(self.read("main.baseline"), SHA1 + "\n")

    def test_missing_previous_or_missing_image_refuses_without_changes(self):
        missing = self.run_script("z12_rollback", "--apply")
        self.assertNotEqual(missing.returncode, 0)
        self.assertEqual(self.read("image.env"), self.tag(SHA1))
        (self.root / "image.previous.env").write_text(self.tag(SHA2))
        (self.root / "images").write_text(
            "ghcr.io/zaraherehehe/amrtrace-studio-api:sha-" + SHA2 + "\n")
        unavailable = self.run_script("z12_rollback", "--apply")
        self.assertNotEqual(unavailable.returncode, 0)
        self.assertIn("Missing previous-release image", unavailable.stderr)
        self.assertEqual(self.read("image.env"), self.tag(SHA1))
        self.assertFalse((self.root / "deploy.log").exists())


if __name__ == "__main__":
    unittest.main()
