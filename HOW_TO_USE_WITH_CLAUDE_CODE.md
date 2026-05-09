# How to use this project with Claude Code

## On your Ubuntu laptop

### 1. Install Claude Code (if you haven't yet)

```bash
npm install -g @anthropic-ai/claude-code
```

(Requires Node.js 18+. If you don't have it: `sudo apt install nodejs npm`.)

### 2. Drop this folder somewhere sensible

```bash
mkdir -p ~/projects
cp -r autoresponder-project ~/projects/autoresponder
cd ~/projects/autoresponder
```

### 3. Open Claude Code in this directory

```bash
claude
```

### 4. First prompt to give Claude Code

Paste this verbatim:

> Read README.md, then SPEC.md, then TESTING.md, then DEPLOYMENT.md. After reading all four, summarize the architecture in 5 bullet points and list any questions you have before implementing. Do not write code yet.

This forces Claude Code to load the full context before it starts. Answer its questions, then say:

> Implement the project per SPEC.md. Use the code sketches as starting points but improve them — add type hints, docstrings, proper logging, error handling, atomic state writes, and graceful shutdown as the spec requires. Build the inline-keyboard control bot, the daily heartbeat, and the error notification mechanism. After you're done, run a syntax check on every Python file and fix anything broken.

### 5. Iterate

Once it's done:
- Try `docker compose build` — if it fails, paste the error to Claude Code.
- Run through `TESTING.md` Phase 1 step by step. Whenever something doesn't behave as expected, describe it to Claude Code and let it fix.

## Tips for working with Claude Code on this project

- **Commit after every working milestone.** `git init` in the folder right at the start, then commit after Phase 1 passes, after Signal works, after polish is done. If Claude Code makes a change that breaks things, you can `git diff` or `git reset` cleanly.

- **Don't let it scope-creep.** The spec lists "out of scope" items deliberately. If Claude Code suggests adding a vacation-end-date or per-contact whitelist, push back unless you actually want it.

- **Ask it to explain.** You're learning Python — when it produces something clever (decorators, asyncio patterns, context managers), ask it to explain *why* it chose that pattern. Good investment.

- **Run tests yourself.** The acceptance criteria in SPEC.md are concrete. Walk through them with Claude Code one at a time rather than trusting "I implemented it, it should work."

- **Keep `.env` out of context.** When debugging, don't paste your real `TG_API_HASH` or bot token into the chat. Use the `.env.example` placeholders.

## When you hit Phase 4 (deploying to your friend)

- The `data/userbot.session` and `signal-data/` folders are extremely sensitive. They are equivalent to having login access to his accounts.
- Don't commit them. The `.gitignore` excludes them already.
- When you SCP to his QNAP, do it over a trusted network or via VPN.
