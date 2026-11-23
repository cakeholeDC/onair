import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parent
TAG = "v2.0.0"
COMMIT = "a" * 40
OTHER_COMMIT = "b" * 40
MANIFEST = ".release-please-manifest.json"
ARCHIVES = [f"onair-{TAG}-darwin-{arch}.tar.gz" for arch in ("arm64", "amd64")]

GIT = """#!/bin/bash
case "$1" in
  diff) printf '%s' "$CHANGED" ;;
  show)
    if [[ "$2" == "$CURRENT_COMMIT:$MANIFEST" ]]; then
      printf '%s' "$VERSION_CONTENTS"
    else
      printf '%s' "$PREVIOUS_CONTENTS"
    fi
    ;;
  ls-tree) printf '%s' "$PREVIOUS_MANIFEST" ;;
  ls-remote) printf '%s' "$REMOTE_REFS" ;;
  *) exit 2 ;;
esac
"""

GH = """#!/bin/bash
case "$1 $2 $3" in
  'api --paginate --slurp') printf '[[%s]]' "$EXISTING_RELEASE" ;;
  'api --method PATCH'|'release upload '*) printf '%s\\n' "$*" >> "$CALL_LOG" ;;
  *) exit 2 ;;
esac
"""


class ReleaseTest(unittest.TestCase):
    def test_workflow_compares_pr_base_after_branch_rewrite(self):
        workflow = (SCRIPTS.parent / "workflows" / "release.yaml").read_text()
        expression = re.search(r"BEFORE_SHA: \$\{\{ (.+?) \}\}", workflow).group(1)
        # Both SHAs exist in a PR synchronize payload, even when the previous
        # head commit has become unreachable after the bot rewrites its branch.
        for event, context, expected in [
            ("pull_request", {"github.event.before": "unreachable-head",
                              "github.event.pull_request.base.sha": OTHER_COMMIT}, OTHER_COMMIT),
            ("push", {"github.event.before": OTHER_COMMIT}, OTHER_COMMIT),
        ]:
            with self.subTest(event=event):
                candidates = [context.get(path.strip()) for path in expression.split("||")]
                self.assertEqual(next(filter(None, candidates)), expected)

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.log = self.root / "calls"
        self.env = {
            **os.environ,
            "PATH": f"{self.root}:{os.environ['PATH']}",
            "CURRENT_COMMIT": COMMIT,
            "MANIFEST": MANIFEST,
            "CHANGED": MANIFEST,
            "VERSION_CONTENTS": json.dumps({".": TAG[1:]}),
            "PREVIOUS_CONTENTS": json.dumps({".": "1.0.0"}),
            "PREVIOUS_MANIFEST": MANIFEST,
            "REMOTE_REFS": "",
            "EXISTING_RELEASE": json.dumps(self.release()),
            "CALL_LOG": str(self.log),
            "GH_REPO": "example/onair",
        }
        for executable, script in {"gh": GH, "git": GIT}.items():
            path = self.root / executable
            path.write_text(script)
            path.chmod(0o755)
        for archive in ARCHIVES:
            (self.root / archive).write_text(archive)

    def release(self, **fields):
        return {"id": 123, "tag_name": TAG, "target_commitish": COMMIT,
                "draft": True, "assets": [], **fields}

    def invoke(self, script, *args):
        return subprocess.run(["bash", SCRIPTS / script, *args], cwd=self.root,
                              env=self.env, capture_output=True, text=True)

    def publish(self):
        return self.invoke("publish-release.sh", TAG, COMMIT, ".")

    def test_version_outputs_tag_when_changed(self):
        result = self.invoke("release-version.sh", OTHER_COMMIT, COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, f"tag={TAG}\n")

    def test_version_skips_unchanged_push(self):
        self.env["CHANGED"] = ""
        result = self.invoke("release-version.sh", OTHER_COMMIT, COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_version_skips_initial_manifest(self):
        self.env["PREVIOUS_MANIFEST"] = ""
        result = self.invoke("release-version.sh", OTHER_COMMIT, COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_version_skips_manifest_edit_with_same_version(self):
        self.env["PREVIOUS_CONTENTS"] = self.env["VERSION_CONTENTS"]
        result = self.invoke("release-version.sh", OTHER_COMMIT, COMMIT)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")

    def test_version_rejects_invalid_tag(self):
        self.env["VERSION_CONTENTS"] = json.dumps({".": "02.0.0\nextra=output"})
        result = self.invoke("release-version.sh", OTHER_COMMIT, COMMIT)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")

    def test_publish_looks_up_existing_draft(self):
        result = self.invoke("publish-release.sh", TAG, "--lookup")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "123\n")
        self.assertFalse(self.log.exists())

    def test_publish_requires_a_release_please_draft(self):
        self.env["EXISTING_RELEASE"] = ""
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("did not create draft", result.stderr)
        self.assertFalse(self.log.exists())

    def test_publish_uploads_all_assets_before_publishing(self):
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.log.read_text().splitlines()
        self.assertEqual(calls[:3], [f"release upload {TAG} {asset}"
                                     for asset in [*ARCHIVES, "SHA256SUMS"]])
        self.assertIn("releases/123 -F draft=false", calls[3])

    def test_publish_refuses_tag_on_different_commit(self):
        self.env["REMOTE_REFS"] = f"{OTHER_COMMIT}\trefs/tags/{TAG}"
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already points", result.stderr)
        self.assertFalse(self.log.exists())

    def test_publish_skips_completed_release_with_annotated_tag(self):
        self.env["REMOTE_REFS"] = (f"{OTHER_COMMIT}\trefs/tags/{TAG}\n"
                                   f"{COMMIT}\trefs/tags/{TAG}^{{}}")
        self.env["EXISTING_RELEASE"] = json.dumps(self.release(draft=False))
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.log.exists())

    def test_publish_refuses_draft_for_different_commit(self):
        self.env["EXISTING_RELEASE"] = json.dumps(self.release(target_commitish=OTHER_COMMIT))
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("targets a different commit", result.stderr)
        self.assertFalse(self.log.exists())

    def test_publish_resumes_draft_with_matching_asset(self):
        archive = ARCHIVES[0]
        digest = hashlib.sha256((self.root / archive).read_bytes()).hexdigest()
        self.env["EXISTING_RELEASE"] = json.dumps(self.release(
            assets=[{"name": archive, "digest": f"sha256:{digest}"}]))
        result = self.publish()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.log.read_text().splitlines()[:2],
                         [f"release upload {TAG} {ARCHIVES[1]}", f"release upload {TAG} SHA256SUMS"])

    def test_publish_refuses_to_overwrite_asset(self):
        self.env["EXISTING_RELEASE"] = json.dumps(self.release(
            assets=[{"name": ARCHIVES[0], "digest": "sha256:wrong"}]))
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already has a different", result.stderr)
        self.assertFalse(self.log.exists())

    def test_publish_requires_both_archives(self):
        (self.root / ARCHIVES[1]).unlink()
        result = self.publish()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.log.exists())
