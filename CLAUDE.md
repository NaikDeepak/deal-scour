# CLAUDE.md

@AGENTS.md

## Claude Code–specific notes

- **Never Read `prototype/dealscour_v3.html` whole.** Line 136 is an ~870 KB base64 image. Use
  `grep -n` and `sed -n 'A,Bp' prototype/dealscour_v3.html | cut -c1-200`.
- Use the docs as your working memory. Before proposing architecture, check `docs/DECISIONS.md`, and don't
  re-litigate an accepted ADR unless the user asks. Record new decisions as an ADR rather than only in chat.
- For optimizer work, read `docs/BASKET_OPTIMIZER.md` fully first. It defines the objective, offer kinds and
  the golden examples that the tests encode.
- When the user describes a new offer they saw ("Flipkart ₹100 off on ₹999 with Axis card"), map it onto the
  offer-kind table in `docs/BASKET_OPTIMIZER.md` §3. If it doesn't fit, propose a new kind using the
  playbook in AGENTS.md §7.
- The user shops in ₹, pincode 411018 by default, and the app is shared with family and friends. Write UI copy
  in plain English and keep it short. Rupee amounts look like `₹1,250`, never `Rs.` or `INR 1250.0`.
- Default Claude model for optional LLM features (free-text list parsing, ADR-016): `claude-haiku-5-5`.
  These features are off by default and must have a monthly spend cap.

## Working with other agents (you are the lead)
<!-- agent-notepad protocol -->
You lead the other coding agents on this repo. Follow "Working with other agents" in AGENTS.md. The human
only describes what to build and watches; you do the rest.

- **agy (Antigravity) builds**, interactively in tmux:
  - one worktree per task: `git worktree add ../<repo>-wt-agy -b feat/<name>` (reuse it if it exists)
  - start once: `tmux new-session -d -s agy -c ../<repo>-wt-agy 'agy --model gemini-3.8-flash-high'`
    (name the model: agy's logs don't record it, and the usage import needs it; `agy models` lists them); the human watches with `tmux attach -t agy`
  - send work: `tmux send-keys -t agy '<text>' Enter`; read its screen: `tmux capture-pane -t agy -p`
  - while it works, run `scripts/watch-agent.sh agy agy claude 40` in the background; it approves safe commands and
    returns on a HANDOFF, a risky prompt (decide it, or ask the human) or a timeout
- **codex reviews**, read-only: `codex exec --sandbox read-only -o /tmp/codex-review.txt "<prompt>"`
  (add `--json >> .collab/codex-<task>.jsonl` to capture its token usage; `>>` keeps every review round)
- **Each task:** write a spec from `docs/tasks/_template.md` (exact files, numbered test cases) → post it with
  `scripts/collab.sh post claude agy "TASK: …"` and a tmux nudge → review the handoff diff (only the spec's files?)
  → codex review → run the full test suite yourself → open a PR and tell the human.
- **Track usage per task** (who used which model, tokens, cost). After each merge:
  - yourself: `scripts/collab.sh usage-import claude claude-code latest --since <task start, ISO UTC> --note "<task>"`
  - codex: run reviews with `--json >> .collab/codex-<task>.jsonl`, then
    `scripts/collab.sh usage-import codex codex-json .collab/codex-<task>.jsonl --note "<task>"` (model is found in codex's own log)
  - agy: `scripts/collab.sh usage-import agy agy latest --model <the model you started it with> --since <task start> --note "<task>"`
- **Finish every feature with a summary for the human** (after the merge or PR, after the usage imports): run
  `scripts/collab.sh summary "<task>"` and show its output in your final message: timeline, time taken, review rounds,
  and who used which model, with tokens and cost. Add one line each on what the reviews found and what you fixed
  yourself. Say that costs are pay-as-you-go API prices, not subscription spend.
- If a tool isn't installed or signed in, do that part yourself and say so.
- Never deploy or run production migrations unless the human says so. No secrets or personal data in the notepad.
