import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    "build_blog", Path(__file__).with_name("build-blog.py")
)
blog = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blog)


class BlogPublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.patch = patch.object(blog, "ROOT", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        (self.root / "published").mkdir()
        (self.root / "posts").mkdir()
        (self.root / "index.qmd").write_text(
            "| [Existing note](published/note.html) | Research |\n"
        )
        (self.root / "published/note.qmd").write_text(
            "---\ntitle: Existing note\ndate: 2024-01-01\n---\n"
        )
        self.metadata = {
            "posts/update.html": {
                "kind": "post", "title": "An update",
                "topics": ["Research", "Data"],
            }
        }

    def write_post(self, draft=False):
        flag = "draft: true\n" if draft else ""
        (self.root / "posts/update.qmd").write_text(
            "---\ntitle: An update\ndate: 2026-09-07\n" + flag + "---\n"
        )
        (self.root / "_blog-metadata.json").write_text(json.dumps(self.metadata))

    def test_drafts_stay_out_until_explicit_preview(self):
        self.write_post(draft=True)
        self.assertEqual([p["href"] for p in blog.collect_posts()],
                         ["published/note.html"])
        self.assertEqual([p["href"] for p in blog.collect_posts(include_drafts=True)],
                         ["posts/update.html", "published/note.html"])

    def test_posts_join_archive_without_being_added_to_note_collection(self):
        self.write_post()
        posts = blog.collect_posts()
        self.assertEqual(posts[0]["href"], "posts/update.html")
        self.assertEqual(posts[0]["topics"], ["Research", "Data"])
        self.assertEqual(len(posts), 2)

    def test_duplicate_registration_is_reported(self):
        self.write_post()
        with (self.root / "index.qmd").open("a") as f:
            f.write("| [An update](posts/update.html) | Research |\n")
        with self.assertRaisesRegex(ValueError, "Duplicate collection entry"):
            blog.collect_posts()


if __name__ == "__main__":
    unittest.main()
