# Region mentions

`region_mentions.json` is the version-controlled list of people to mention for each generator region.
Each region code maps to an array of strings. Placeholder handles such as `@testuser1` are rendered as text. Replace them with real Slack member IDs (for example `U0123456789`) to produce notifications.

The generator loads this file through `/api/region-mentions`. Edits and exclusions in the UI apply to the current page session and are sent with each request; they do not overwrite this file. An explicitly empty list means no mentions. Changes to the default list should be made here and committed to Git.

Channel routing stays in the existing local `slack_routes.json` / environment configuration. User lists from that older channel-routing file are not used by the case sender.
