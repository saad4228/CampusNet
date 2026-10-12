import unittest

from campusnet.discovery import resolve_portal_redirect


class PortalRedirectTests(unittest.TestCase):
    def setUp(self):
        self.base_url = "https://192.168.55.253:1003/fgtauth"
        self.probe_url = "http://connectivitycheck.gstatic.com/generate_204"

    def test_accepts_same_fortigate_auth_redirect_with_temporary_query(self):
        url = resolve_portal_redirect(
            self.base_url,
            self.probe_url,
            "https://192.168.55.253:1003/fgtauth?fresh-token-value",
        )
        self.assertEqual(url, "https://192.168.55.253:1003/fgtauth?fresh-token-value")

    def test_rejects_redirect_to_another_host(self):
        url = resolve_portal_redirect(
            self.base_url,
            self.probe_url,
            "https://attacker.example/fgtauth?token",
        )
        self.assertIsNone(url)

    def test_rejects_wrong_path(self):
        url = resolve_portal_redirect(
            self.base_url,
            self.probe_url,
            "https://192.168.55.253:1003/other-page?token",
        )
        self.assertIsNone(url)

    def test_rejects_missing_location(self):
        self.assertIsNone(resolve_portal_redirect(self.base_url, self.probe_url, None))

    def test_finds_absolute_fortigate_url_in_intercepted_html_body(self):
        body = '<script>window.location = "https://192.168.55.253:1003/fgtauth?fresh-body-token";</script>'
        self.assertEqual(
            resolve_portal_redirect(self.base_url, self.probe_url, None, body),
            "https://192.168.55.253:1003/fgtauth?fresh-body-token",
        )

    def test_finds_root_relative_fortigate_url_in_html_body(self):
        body = '<meta http-equiv="refresh" content="0; url=/fgtauth?fresh-meta-token">'
        self.assertEqual(
            resolve_portal_redirect(self.base_url, self.probe_url, None, body),
            "https://192.168.55.253:1003/fgtauth?fresh-meta-token",
        )

    def test_rejects_static_login_url_without_token(self):
        body = '<script>window.location = "https://192.168.55.253:1003/fgtauth";</script>'
        self.assertIsNone(resolve_portal_redirect(self.base_url, self.probe_url, None, body))

    def test_rejects_wrong_origin_even_when_found_in_body(self):
        body = '<a href="https://attacker.example/fgtauth?token">login</a>'
        self.assertIsNone(resolve_portal_redirect(self.base_url, self.probe_url, None, body))


if __name__ == "__main__":
    unittest.main()
