# Webcam (Taco Cam): how it was built

Transcripts live in `~/.claude/projects/D--ClaudeProjects-Webcam/<id>*.jsonl`. `WORKFLOW.html` is the picture
of this record (drawn from `workflow.json`).

## 2026-10-25: Team build + first real-phone run

**At a glance:** 5 sessions: 1 orchestrator, 3 builder stations in the shared working tree (no worktrees),
then 1 follow-up session that did the Checker's job (the Checker station never started).

```
orchestrator 61f2a5e9 (CONTRACT.md + specs/*.md briefs)
   ├─> iPhone station 4ee308cf ──┐ (stopped at push: gh token lacked `workflow` scope)
   ├─> PC engine station e0b71d0e┼─> follow-up 24137721: checker review + 4 iOS fixes -> push -> green build
   └─> PC app station 49cc3c6e ──┘    -> IPA -> iloader install -> real-phone run -> Whatnot settings
```

**Timeline (local time)**

| Time | What happened |
|---|---|
| 15:21 | User: "Build with Nodeterm orchestration" an Iriun-like app with 0.5x zoom, USB first, no worktrees |
| 15:21-17:24 | Orchestrator settles choices with the user (iPhone 11+, GitHub macOS build, Sideloadly), writes CONTRACT.md + briefs |
| 17:24 | Three stations start in parallel |
| 17:44 | iPhone station commits the app; push refused (`workflow` scope) |
| 17:58 | App station reports success (60 app tests) |
| 18:12 | Engine station reports success (185 engine tests, vcam verified) |
| 18:39 | iPhone station ends waiting for the user's GitHub login fix; no outcome reported |
| 18:44 | User asks "are we done?" in a new session (24137721) |
| ~19:00 | User runs `gh auth refresh -s workflow`; push; build green; IPA downloaded |
| ~19:20-19:40 | Sideloadly -80046; iloader installs the app; first real-phone connection and frame |
| 19:40-20:22 | 4K lag measured, Whatnot settings applied, OBS settings checked against Whatnot/IVS and left as they are |

**Every session**

| Stage | Session | Role | Time | Files | What it did | Outcome |
|---|---|---|---|---|---|---|
| Lead | 61f2a5e9 | Orchestrator | 15:21-17:36 | 8 | CONTRACT.md, specs/ios, engine, app, qa briefs, NOTES.md | done |
| Build | 4ee308cf | iPhone station | 17:24-18:39 | 20 | Swift app, XcodeGen project, CI workflow, INSTALL_IPHONE.md, 14 iOS tests | problem (blocked at push) |
| Build | e0b71d0e | PC engine station | 17:24-19:08 | 28 | protocol, usbmux, link, decoder, pipeline, vcam, engine, fake phone, vcam install scripts, 185 tests | done |
| Build | 49cc3c6e | PC app station | 17:24-18:13 | 17 | tkinter window, settings, README, launchers, 60 app tests | done |
| Fix | 24137721 | Follow-up (did the Checker's job) | 18:44-20:22 | 10 | Swift review vs contract, 4 iOS fixes, push + build, docs/QA.md, real-phone tests, 4K benchmark, Whatnot settings, phone-memory test | done |

**What went wrong, and the lesson**
- The iPhone station's push needed a GitHub permission only the user can grant; the Checker was gated on
  that station's success, so the chain stalled silently. Lesson: check `gh auth status` for the `workflow`
  scope before a team run that must push a workflow file.
- Sideloadly's Apple login broke (Apple change on 2026-10-21, -80046); iloader worked. Check current
  sideload-tool status before giving install instructions.
- Advice nearly broke the Whatnot stream: OBS output settings came from Whatnot's own tool. Check where
  existing settings came from before suggesting changes.
