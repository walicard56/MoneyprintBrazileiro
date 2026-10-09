# Twitter Bot

This bot is designed to automate the process of growing a Twitter account. When creating an account, provide the path to the Brave profile that is logged into X. Find it at `brave://version` under **Profile Path**. The bot will post tweets based on the subject you provided during account creation.

## Relevant Configuration

In your `config.json`, you need the following attributes filled out, so that the bot can function correctly.

```json
{
  "twitter_language": "Any Language, formatting doesn't matter",
  "headless": true,
  "llm": "The Large Language Model you want to use, check Configuration.md for more information",
}
```