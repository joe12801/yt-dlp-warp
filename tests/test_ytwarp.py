"""纯标准库单元测试：python -m unittest discover -s tests -v"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import ytwarp  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "cookie_tool", ROOT / "scripts" / "cookie-editor-to-netscape.py"
)
cookie_tool = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(cookie_tool)


def base_opts(**kwargs) -> dict:
    o = {
        "base": ["yt-dlp"],
        "proxy": ytwarp.DEFAULT_PROXY,
        "cookies": "",
        "cookies_from_browser": "",
        "format": ytwarp.DEFAULT_FORMAT,
        "merge": ytwarp.DEFAULT_MERGE,
        "output": "downloads/%(title).200B [%(id)s].%(ext)s",
        "sub_langs": ytwarp.DEFAULT_SUB_LANGS,
        "retries": 5,
        "limit_rate": "",
        "ffmpeg": "",
        "playlist": False,
        "playlist_end": None,
        "audio_only": False,
        "subs": False,
        "embed_subs": True,
        "thumbnail": False,
        "js": None,
        "js_supported": False,
        "list_formats": False,
        "simulate": False,
        "extra": [],
    }
    o.update(kwargs)
    return o


class TestDotEnv(unittest.TestCase):
    def test_load_dotenv_does_not_override_explicit_environment(self):
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / ".env"
            p.write_text(
                "# comment\n"
                "YTWARP_PROXY=socks5://127.0.0.1:40001\n"
                "export YTWARP_RETRIES='9'\n"
                "YTWARP_COOKIES=\"cookies.txt\"\n"
                "IRRELEVANT=x\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"YTWARP_PROXY": "explicit"}, clear=False):
                ytwarp.load_dotenv(p)
                self.assertEqual(os.environ["YTWARP_PROXY"], "explicit")
                self.assertEqual(os.environ["YTWARP_RETRIES"], "9")
                self.assertEqual(os.environ["YTWARP_COOKIES"], "cookies.txt")
                self.assertNotIn("IRRELEVANT", os.environ)
            for key in ("YTWARP_RETRIES", "YTWARP_COOKIES"):
                os.environ.pop(key, None)


class TestBuildCommand(unittest.TestCase):
    def test_default_uses_warp_proxy_and_no_cookies(self):
        cmd = ytwarp.build_command(base_opts(), ["https://youtu.be/abc"])
        self.assertIn("--proxy", cmd)
        self.assertIn(ytwarp.DEFAULT_PROXY, cmd)
        self.assertNotIn("--cookies", cmd)
        self.assertNotIn("--cookies-from-browser", cmd)
        self.assertIn("--no-playlist", cmd)
        self.assertIn("-f", cmd)
        self.assertIn("--merge-output-format", cmd)
        self.assertEqual(cmd[-1], "https://youtu.be/abc")

    def test_no_proxy_forces_direct_and_ignores_env_proxy(self):
        cmd = ytwarp.build_command(base_opts(proxy=""), ["URL"])
        self.assertEqual(cmd[cmd.index("--proxy") + 1], "")

    def test_cookie_uses_snapshot_path_not_original(self):
        cmd = ytwarp.build_command(
            base_opts(cookies="/tmp/ytwarp-cookies-xyz/cookies.txt"), ["URL"]
        )
        self.assertIn("--cookies", cmd)
        self.assertIn("/tmp/ytwarp-cookies-xyz/cookies.txt", cmd)
        self.assertNotIn("/home/user/cookies.txt", cmd)

    def test_audio_only_and_subs_flags(self):
        cmd = ytwarp.build_command(
            base_opts(audio_only=True, subs=True, embed_subs=True, sub_langs="zh-Hans,en"),
            ["URL"],
        )
        for flag in ("-x", "--audio-format", "--write-subs", "--write-auto-subs",
                     "--sub-langs", "--embed-subs"):
            self.assertIn(flag, cmd)
        self.assertNotIn("-f", cmd)

    def test_simulate_list_formats_and_extra_args(self):
        cmd = ytwarp.build_command(
            base_opts(list_formats=True, simulate=True, extra=["--write-info-json", "--no-mtime"]),
            ["URL"],
        )
        for flag in ("-F", "--simulate", "--skip-download", "--write-info-json", "--no-mtime"):
            self.assertIn(flag, cmd)

    def test_js_runtime_only_when_cli_supports_it(self):
        cmd = ytwarp.build_command(base_opts(js="node", js_supported=True), ["URL"])
        self.assertIn("--js-runtimes", cmd)
        cmd = ytwarp.build_command(base_opts(js="node", js_supported=False), ["URL"])
        self.assertNotIn("--js-runtimes", cmd)

    def test_playlist_end_only_with_playlist(self):
        self.assertIn("--playlist-end", ytwarp.build_command(
            base_opts(playlist=True, playlist_end=10), ["URL"]))
        self.assertIn("--no-playlist", ytwarp.build_command(
            base_opts(playlist=False, playlist_end=10), ["URL"]))


class TestSplitExtraArgs(unittest.TestCase):
    def test_basic_flags(self):
        self.assertEqual(
            ytwarp.split_extra_args("--write-info-json --no-mtime"),
            ["--write-info-json", "--no-mtime"],
        )
        self.assertEqual(ytwarp.split_extra_args("   "), [])

    def test_windows_backslash_path_is_preserved(self):
        with mock.patch.object(ytwarp.os, "name", "nt"):
            out = ytwarp.split_extra_args('--ffmpeg-location "C:\\ffmpeg\\bin"')
        self.assertEqual(out, ["--ffmpeg-location", "C:\\ffmpeg\\bin"])


class TestCookieSnapshot(unittest.TestCase):
    def test_snapshot_is_read_only_copy(self):
        with tempfile.TemporaryDirectory() as td:
            src = pathlib.Path(td) / "cookies.txt"
            original = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret\n"
            src.write_text(original, encoding="utf-8")
            snap = ytwarp.make_cookie_snapshot(src)
            try:
                self.assertNotEqual(snap, src)
                self.assertEqual(snap.read_text(encoding="utf-8"), original)
                snap.write_text("OVERWRITTEN", encoding="utf-8")
                self.assertEqual(src.read_text(encoding="utf-8"), original)
            finally:
                shutil.rmtree(snap.parent, ignore_errors=True)
            self.assertTrue(src.exists())


class TestCookieTool(unittest.TestCase):
    def test_json_normalizes_domain_and_keeps_httponly(self):
        raw = json.dumps([{
            "name": "SAPISID", "value": "secret-value", "domain": "youtube.com",
            "path": "/", "secure": True, "httpOnly": True, "hostOnly": True,
            "expirationDate": 1999999999,
        }, {
            "name": "PREF", "value": "x", "domain": ".youtube.com", "path": "/",
            "secure": True, "expirationDate": 1999999999,
        }])
        fmt, cookies = cookie_tool.detect_and_parse(raw)
        self.assertEqual(fmt, "Cookie-Editor JSON")
        self.assertEqual(len(cookies), 2)
        self.assertEqual(cookies[0]["domain"], "youtube.com")
        self.assertTrue(cookies[0]["httpOnly"])
        self.assertEqual(cookies[1]["domain"], ".youtube.com")

    def test_write_netscape_filters_domains_and_marks_httponly(self):
        cookies = [
            {"domain": ".youtube.com", "path": "/", "secure": True,
             "httpOnly": True, "expires": 0, "name": "SAPISID", "value": "s3cr3t"},
            {"domain": ".example.com", "path": "/", "secure": False,
             "httpOnly": False, "expires": 0, "name": "TRACK", "value": "nope"},
        ]
        selected = [c for c in cookies if cookie_tool.keep(c["domain"])]
        self.assertEqual(len(selected), 1)
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td) / "cookies.txt"
            n = cookie_tool.write_netscape(selected, out)
            self.assertEqual(n, 1)
            text = out.read_text(encoding="utf-8")
            self.assertIn("#HttpOnly_.youtube.com", text)
            self.assertIn("SAPISID", text)
            self.assertNotIn("TRACK", text)

    def test_header_string_input(self):
        fmt, cookies = cookie_tool.detect_and_parse("A=1; B=2")
        self.assertEqual(fmt, "Header 字符串")
        self.assertEqual([c["name"] for c in cookies], ["A", "B"])

    def test_netscape_roundtrip(self):
        original = (
            "# Netscape HTTP Cookie File\n"
            "#HttpOnly_.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret\n"
        )
        fmt, cookies = cookie_tool.detect_and_parse(original)
        self.assertEqual(fmt, "Netscape")
        self.assertTrue(cookies[0]["httpOnly"])
        self.assertEqual(cookies[0]["value"], "secret")


class TestWipeNodeOptions(unittest.TestCase):
    def test_removes_injected_node_options_by_default(self):
        with mock.patch.dict(os.environ, {"NODE_OPTIONS": "--require=shim"}, clear=False):
            os.environ.pop("YTWARP_KEEP_NODE_OPTIONS", None)
            ytwarp.wipe_node_options()
            self.assertNotIn("NODE_OPTIONS", os.environ)

    def test_can_keep(self):
        with mock.patch.dict(os.environ,
                            {"NODE_OPTIONS": "x", "YTWARP_KEEP_NODE_OPTIONS": "1"},
                            clear=False):
            ytwarp.wipe_node_options()
            self.assertEqual(os.environ["NODE_OPTIONS"], "x")


if __name__ == "__main__":
    unittest.main()
