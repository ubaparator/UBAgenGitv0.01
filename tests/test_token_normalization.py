import unittest

from redirect_bot import normalize_discord_token


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


if __name__ == "__main__":
    unittest.main()
