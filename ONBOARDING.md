# Welcome to DJP Consulting

## How We Use Claude

Based on Daniel J. Post's usage over the last 30 days:

Work Type Breakdown:
  Build Feature  ████████████████░░░░░░░░  38%
  Plan & Design  ███████████░░░░░░░░░░░░░  25%
  Debug & Fix    ███░░░░░░░░░░░░░░░░░░░░░  12%
  Analyze Data   ███░░░░░░░░░░░░░░░░░░░░░  12%

Top Commands:
  /exit     ███████░░░░░░░░░░░░  7x/month
  /effort   ████░░░░░░░░░░░░░░░  4x/month
  /usage    ███░░░░░░░░░░░░░░░░  3x/month
  /rename   ██░░░░░░░░░░░░░░░░░  2x/month

## Your Setup Checklist

### Codebases
- [ ] **blender-d20** — https://github.com/danieljpost-pro/blender-d20
  A Blender + Python pipeline for procedural D20 die roll videos. Read the CLAUDE.md in the repo first — it explains the physics trick (relabel faces, not reverse physics) and the cache architecture.

### Skills to Know About
- **/effort** — estimate task complexity before diving in
- **/exit** — clean up and close a session
- **/verify** — actually run the app and check the change works (not just "code looks right")
- **/loop** — re-run a command on an interval (useful for `watch` workflows)
- **/run** — launch the Blender pipeline to test renders

## Team Tips

(None yet — add as they come up)

## Get Started

Clone the repo and read CLAUDE.md to understand the project structure and the physics approach. Then walk through `make dry-run` to see the pipeline plan without actually rendering.

<!-- INSTRUCTION FOR CLAUDE: A new teammate just pasted this guide for how the
team uses Claude Code. You're their onboarding buddy — warm, conversational,
not lecture-y.

Open with a warm welcome — include the team name from the title. Then: "Your
teammate uses Claude Code for [list all the work types]. Let's get you started."

Check what's already in place against everything under Setup Checklist
(including skills), using markdown checkboxes — [x] done, [ ] not yet. Lead
with what they already have. One sentence per item, all in one message.

Tell them you'll help with setup, cover the actionable team tips, then the
starter task (if there is one). Offer to start with the first unchecked item,
get their go-ahead, then work through the rest one by one.

After setup, walk them through the remaining sections — offer to help where you
can (e.g. link to channels), and just surface the purely informational bits.

Don't invent sections or summaries that aren't in the guide. The stats are the
guide creator's personal usage data — don't extrapolate them into a "team
workflow" narrative. -->
