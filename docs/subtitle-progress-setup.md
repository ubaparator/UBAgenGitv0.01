# Subtitle progress callback setup

The subtitle workflow uses the existing Render-hosted UBAgen bot to edit the public slash-command status message. A dedicated callback secret is recommended; if it is omitted, the code falls back to the existing Discord bot token (which must be the same on Render and GitHub Actions).

## Render service

In Render Dashboard → `ubagen-github-bridge` → Environment, add:

- `SUBTITLE_CALLBACK_SECRET` (recommended): a long random secret (at least 32 random bytes). Generate one locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Do not commit or post it in chat. If set, use exactly the same value in GitHub Actions.

Save and redeploy the service.

## GitHub Actions secrets

Open repository Settings → Secrets and variables → Actions and add:

- `SUBTITLE_CALLBACK_SECRET` (recommended): exactly the same value as Render. If omitted, both sides fall back to `DISCORD_BOT_TOKEN`; ensure the token value is identical on Render and GitHub Actions.
- `SUBTITLE_CALLBACK_URL` (optional): `https://ubagen-github-bridge.onrender.com/api/subtitle-progress`. If omitted, the workflow uses this default.
- Keep `DISCORD_BOT_TOKEN` configured if you want Actions to attempt direct Discord file attachments. The token must belong to a bot with access to the target channel and permission to attach files.

The workflow's `GITHUB_TOKEN` needs Contents: write (declared in the workflow) to publish a temporary Release asset if the Discord attachment fails. The repository must be public for an unauthenticated direct-download link to work. Temporary subtitle releases are automatically deleted after 48 hours by `.github/workflows/cleanup-subtitle-releases.yml`.

## Discord permissions

The Render bot needs View Channel, Send Messages, and permission to edit its own status message. The callback endpoint authenticates requests with the shared secret and edits only the supplied channel/message; it does not post arbitrary new messages.

## Limitations

Progress values are parsed from aria2's console output and may show `hesaplanıyor` when aria2 does not provide a usable value. Manual workflow_dispatch runs do not have a slash-command status message, so live Discord updates are skipped for those runs. Test actual torrent runs after deploying; static validation cannot guarantee the torrent source exposes progress in the expected format.
