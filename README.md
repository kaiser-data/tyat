# tend-your-agent-task (tyat) 🌱

[![CI](https://github.com/kaiser-data/tyat/actions/workflows/ci.yml/badge.svg)](https://github.com/kaiser-data/tyat/actions/workflows/ci.yml)

**Tend your tasks and your agent sessions.** One terminal command, `tyat` (alias `t`), that answers *what's waiting on me, where is it, which assistant has it, and what's next*, then takes you there.

```
$ t
⏳ ON YOU
    1  claude  hackathon/collab-agent                        needs you  1h16
    2  claude  products/interview-prep                       your turn    4m
🔄 RUNNING
    3  codex   article_publisher                             running      6m
📋 TASKS  (12 open)
    d  17:00      !!! Send the name-tag list                @…/divisionday/namensschilder
    g  tmrw 10:00 !! Sayproof: record demo video             @hackathons/2026/sayproof
       → deck approved, video next

▶ NEXT  answer claude · hackathon/collab-agent needs you 1h16
  then  start [d] Send the name-tag list 17:00

  ⏎ do next · 1-9 jump · a-z start task · o open folder · r recent · + add · x a done · s a 2h · q quit
›
```

## Why

After a while of agent-assisted work you have a dozen sessions open across as many folders, and some of them have been sitting there waiting for you for an hour. Tasks live in your head or in handoff files nobody re-reads. tyat puts one layer between *projects* and *sessions*: tasks with times, linked to the agent session that works on them.

## What it does

- **Live sessions.** Reads Claude Code's own session state (`~/.claude/sessions`) for busy / waiting / idle, and finds Codex, Gemini, Grok, Cursor and Droid in the process list. Each row shows the folder, the assistant and how long it has been waiting.
- **▶ NEXT.** Ranks everything: sessions that need you, overdue tasks, finished sessions linked to a task, tasks due within 3 hours, priority tasks. Enter does the top one, and `t now` does it with no prompt.
- **Start where the work is.** `t go a` changes into the task's folder and starts the agent with the task (plus the folder's latest `HANDOFF*.md`) as the first prompt. The task remembers the session: next time it jumps to the session if it's open, or resumes the conversation if it has closed.
- **One-key chooser.** Claude, Codex, a [kogitsune](https://github.com/kaiser-data) kit chosen by `kit for`, or resume the folder's last conversation.
- **Agents report back.** The first prompt asks the agent to run `t done a` or `t next a "<next step>"` when it stops, so the board always shows where to pick up.
- **Nudges.** A LaunchAgent sends a macOS notification when a task falls due, or when a session has been waiting on you for 10 minutes or more.
- **Where things stand.** `t handoffs` lists every project's newest handoff with its next step and flags projects that have no task.

## Commands

```
t                         board + ▶ NEXT; enter does it
t now                     do the top recommendation
t add <text> [@folder] [when] [!|!!|!!!]
                          when: today · tomorrow · mon..sun · 14:00 · 2h · 3d · 2026-11-02 · 02.11.
t go <id> [claude|codex|kit:<name>|gemini|grok] [?] [--new]
t open [name]             fuzzy-pick a project folder → start or resume there
t recent                  fuzzy-pick a recent conversation → resume it
t handoffs [days]         newest handoff per project + next step
t page [hours]            HTML page: tasks + publishing calendar ranked by value ÷ effort, a plan for [hours]
t page --publish          + private phone plan with a spoken briefing per block, deployed behind a key
t report                  today since 05:00: done, overdue, due ≤24h, prompts after the stop
t inbox [--claude]        fetch voice memos / notes sent from the phone plan, transcribe, hand to Claude
t check [--apply]         a small model reads the last 72h of commits, handoffs and session transcripts
                          → marks finished tasks done; late tasks move into free slots (TYAT_AUTOCHECK=1: auto at 22:00, 12:00, stop)
t <n>                     jump to session n (focuses its iTerm tab)
t done|next|snooze|rm <id> …    t here    t edit    t install
t help    t --version
```

## Install

macOS, Python 3.10+, [fzf](https://github.com/junegunn/fzf) for the pickers. No other dependencies.

```bash
git clone https://github.com/kaiser-data/tyat && cd tyat
./tyat install     # links tyat + t into ~/.local/bin and loads the notifier LaunchAgent
```

| Variable | Default | |
|---|---|---|
| `TYAT_ROOT` | `~/claude-projects` | where your project folders live (`@folder` is relative to it) |
| `TYAT_TASKS` | `./tasks.md` | the task file: one line per task, hand edits welcome |
| `TYAT_WAIT_MIN` | `10` | minutes before a waiting session triggers a notification |
| `TYAT_SLM` | `claude:haiku` | model for `t check`: `claude:<model>` (headless Claude Code, no hooks/MCP/tools) or `ollama:<model>` (local) |
| `TYAT_CHECK_MIN` | `0.85` | confidence the model needs before a task is marked done |
| `TYAT_AUTOCHECK` | `0` | `1` lets the notifier run `t check --auto` at block starts (off until replan respects appointments and business hours) |

Uninstall the notifier: `launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/dev.tyat.notify.plist`.

## Task file

```markdown
- [ ] Review stars report @products/github-stars-analyzer due:2026-10-27T14:00 pri:1 id:a via:claude sid:<uuid>
  > next: check top 20 candidates
```

Plain Markdown, so any agent can read or edit it. Optional `est:20m` (effort) and `reach:1-5` (how many people it moves) feed the ranking in `t page`: value = 2×reach + priority + urgency, divided by a slowly growing effort term, so a 10-minute high-reach task beats a 3-hour low-reach one. Rows of the [article_publisher](../article_publisher) editorial calendar (`TYAT_PUBLISHER`) join the same ranking, with reach taken from its `docs/priority.json`.

## Phone plan (`t page --publish`)

Writes the same schedule as a phone PWA to `$TYAT_PLAN/public/index.html` (default `./pub-plan`, gitignored): one section per block (now, do, deep, night, sport, stop), checkboxes, copyable `t go` commands and a "🔊 Was jetzt?" button that plays the briefing of the current block. Briefings are rendered with ElevenLabs (`$ELEVENLABS_API_KEY` or `~/.config/elevenlabs/key`) and cached by text, so an unchanged block costs nothing on the next publish. It then runs `wrangler deploy`, but only if `pub-plan/` has a `worker.js` and a `wrangler.jsonc` with `run_worker_first: true`, so every request passes the key check first; a plain static deploy would make the plan public. `--no-voice` and `--no-deploy` skip those steps.

### Daily report and feedback

The phone plan also carries the daily report (`t report`, spoken as "🔊 Bericht") and a feedback card: record a voice memo (🎙) or type a note, and it is stored in the Worker's KV namespace behind the same key. `t inbox` fetches it, transcribes voice memos with ElevenLabs speech-to-text, appends everything to `inbox.md` (gitignored), deletes it remotely, and with `--claude` opens a session that turns it into `t done` / `next` / `snooze` / `add`. The plan URL comes from `$TYAT_PLAN_URL` or `.plan-url`. Worker and config templates: [`plan-template/`](plan-template).

## Development

tyat is a single stdlib-only Python file, so there is nothing to install. To run the checks CI runs:

```bash
ruff check .                              # lint (config in pyproject.toml)
python3 -m unittest discover tests -v     # unit tests: task file, date parsing, ▶ NEXT ranking
TYAT_TASKS=/tmp/t.md ./tyat add try it tomorrow   # smoke test without touching your real tasks.md
```

The tests point `TYAT_TASKS` at a temp file and pin the clock, so they never read or write your task list.

## License

[MIT](LICENSE)
