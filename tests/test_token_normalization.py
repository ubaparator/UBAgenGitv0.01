import unittest

from redirect_bot import normalize_discord_token, github_dispatch_error


class DiscordTokenNormalizationTests(unittest.TestCase):
    def test_plain_token_is_unchanged(self):
        self.assertEqual(normalize_discord_token("abc.def.ghi"), "abc.def.ghi")

    def test_surrounding_whitespace_is_removed(self):
        self.assertEqual(normalize_discord_token("  abc.def.ghi \n"), "abc.def.ghi")

    def test_optional_bot_prefix_is_removed(self):
        self.assertEqual(normalize_discord_token("Bot abc.def.ghi"), "abc.def.ghi")
        self.assertEqual(normalize_discord_token("bot abc.def.ghi"), "abc.def.ghi")

    def test_matching_quotes_are_removed(self):
        self.assertEqual(normalize_discord_token('"abc.def.ghi"'), "abc.def.ghi")
        self.assertEqual(normalize_discord_token("'abc.def.ghi'"), "abc.def.ghi")

    def test_missing_token_is_empty(self):
        self.assertEqual(normalize_discord_token(None), "")
        self.assertEqual(normalize_discord_token("  "), "")


class GitHubDispatchErrorTests(unittest.TestCase):
    def test_403_explains_token_permissions(self):
        message = github_dispatch_error("subtitle dispatch", 403, '{"message":"Resource not accessible by personal access token","status":403}')
        self.assertIn("Contents = Read and write", message)
        self.assertIn("GH_TOKEN", message)

    def test_401_explains_invalid_token(self):
        message = github_dispatch_error("dispatch", 401, '{"message":"Bad credentials"}')
        self.assertIn("HTTP 401", message)

    def test_404_mentions_repository(self):
        message = github_dispatch_error("dispatch", 404, '{"message":"Not Found"}')
        self.assertIn("HTTP 404", message)
        self.assertIn("ubaparator/UBAgenGitv0.01", message)


if __name__ == "__main__":
    unittest.main()
