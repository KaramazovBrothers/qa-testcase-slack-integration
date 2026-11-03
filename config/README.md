# Region mentions

`region_mentions.json` is the version-controlled list of people to mention for each generator region.
Each region code maps to an array of strings. Placeholder handles such as `@testuser1` are rendered as text. Replace them with real Slack member IDs (for example `U0123456789`) to produce notifications.

The generator loads this file through `/api/region-mentions`. Edits and exclusions in the UI apply to the current page session and are sent with each request; they do not overwrite this file. An explicitly empty list means no mentions. Changes to the default list should be made here and committed to Git.

Channel routing stays in the existing local `slack_routes.json` / environment configuration. User lists from that older channel-routing file are not used by the case sender.

## Channel routing (`slack_routes.json`)

`slack_routes.json` is **not** in Git: it holds real channel IDs for your workspace.
Create it from the committed example after cloning:

```sh
cp config/slack_routes.example.json config/slack_routes.json
```

Then replace every placeholder with real values. Each key is a region code from
the generator (`TR`, `KZ`, `RU`, …):

```json
{
  "TR": {"channel_id": "C0123456789", "user_ids": []},
  "default": {"channel_id": "C0987654321", "user_ids": []}
}
```

- `channel_id` — target channel. In Slack: right-click the channel → **Copy link**;
  the ID is the trailing `C…` segment.
- `user_ids` — optional extra mentions; leave `[]` to use
  `SLACK_MENTION_USER_IDS` from `.env` instead.
- `default` — optional fallback for regions that are not listed.

Resolution order in `app/slack_routes.py`: the region entry, then `default`, then
`SLACK_CHANNEL_ID` from `.env`. If none is set, `POST /slack/send-cases` fails with
`No Slack channel configured for region <CODE>`.

The file is read on every send, so edits take effect without a restart.

The app must be invited to each channel (`/invite @YourAppName`) before Slack
delivers `message.channels` / `message.groups` for it; otherwise replies in that
channel's threads never reach `/slack/events`.
