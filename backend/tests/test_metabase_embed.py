"""看板嵌入地址：跟随浏览器当前访问的主机（NAS 双网口场景）。"""

import os
import unittest
from unittest.mock import patch

from app.core.metabase_embed import (
    _FOLLOW_HOST_ENV,
    _embed_base,
    _follow_request_host,
)


class EmbedBaseTest(unittest.TestCase):
    def test_follows_request_host_keeps_configured_port(self):
        base = _embed_base("http://192.168.2.38:13000", "192.168.10.5:18088")
        self.assertEqual(base, "http://192.168.10.5:13000")

    def test_same_host_is_unchanged(self):
        base = _embed_base("http://192.168.2.38:13000", "192.168.2.38:18088")
        self.assertEqual(base, "http://192.168.2.38:13000")

    def test_bare_host_without_port_from_nginx(self):
        # docker/nginx.conf 里是 `proxy_set_header Host $host;`，不带端口
        base = _embed_base("http://192.168.2.38:13000", "192.168.10.5")
        self.assertEqual(base, "http://192.168.10.5:13000")

    def test_container_internal_address_becomes_browser_reachable(self):
        base = _embed_base("http://host.docker.internal:13000", "10.0.0.9")
        self.assertEqual(base, "http://10.0.0.9:13000")

    def test_request_port_is_ignored(self):
        # 浏览器给的是应用端口(18088)，嵌入地址仍要用 Metabase 端口(13000)
        self.assertEqual(
            _embed_base("http://nas:13000", "10.0.0.9"),
            "http://10.0.0.9:13000",
        )
        self.assertEqual(_embed_base("https://nas", "10.0.0.9"), "https://10.0.0.9")

    def test_subpath_and_scheme_preserved(self):
        base = _embed_base("https://nas.example.com:443/metabase", "10.0.0.9")
        self.assertEqual(base, "https://10.0.0.9:443/metabase")

    def test_first_value_of_forwarded_host_list(self):
        base = _embed_base("http://nas:13000", "10.0.0.9, 172.16.0.1")
        self.assertEqual(base, "http://10.0.0.9:13000")

    def test_ipv6_request_host_is_bracketed(self):
        base = _embed_base("http://nas:13000", "[fd00::1]:18088")
        self.assertEqual(base, "http://[fd00::1]:13000")

    def test_empty_request_host_falls_back_to_config(self):
        for value in (None, "", "   "):
            self.assertEqual(_embed_base("http://nas:13000", value), "http://nas:13000")

    def test_broken_config_is_returned_as_is(self):
        self.assertEqual(_embed_base("not-a-url", "10.0.0.9"), "not-a-url")
        self.assertEqual(_embed_base("", "10.0.0.9"), "")


class FollowHostSwitchTest(unittest.TestCase):
    def test_enabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(_FOLLOW_HOST_ENV, None)
            self.assertTrue(_follow_request_host())

    def test_can_be_disabled(self):
        for value in ("0", "false", "NO", "off"):
            with patch.dict(os.environ, {_FOLLOW_HOST_ENV: value}):
                self.assertFalse(_follow_request_host())

    def test_disabled_keeps_written_address(self):
        with patch.dict(os.environ, {_FOLLOW_HOST_ENV: "0"}):
            base = _embed_base("http://192.168.2.38:13000", "192.168.10.5")
        self.assertEqual(base, "http://192.168.2.38:13000")


if __name__ == "__main__":
    unittest.main()
