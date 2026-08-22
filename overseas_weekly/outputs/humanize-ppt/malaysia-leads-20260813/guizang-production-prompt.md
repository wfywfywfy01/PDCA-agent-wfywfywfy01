# Guizang Production Prompt

> Humanize PPT stops here. The next agent must follow
> `~/.agents/skills/guizang-ppt-skill/SKILL.md` end to end.
> Do not reimplement Guizang inside Humanize. Do not import the
> Guizang template into Humanize. Do not post-process the rendered HTML
> with Humanize-owned bridges — Guizang owns its own navigation.

## Deck

- Title: 马来西亚市场：线索全生命周期，不是客户管理
- Source: d:\经销商PDCA\overseas_weekly\inputs\malaysia\2026-08-13_humanize_source.md
- Language: zh
- Style: A
- Theme preset: ink-classic (Ink Classic (墨水经典) — the verified known-good baseline at examples/03-codex-guizang-native-ink-classic/)

- Slides: 7

## Style files (use the ones for Style A)

- template: `assets/template.html`
- layouts: `references/layouts.md`
- themes: `references/themes.md`
- lock: (none — Style A is the flexible track)
- validator: `guizang's own Style A visual QA checklist (see references/guizang-material-qa.md)`
- Apply theme preset: `ink-classic` from references/themes.md


## Hard rules

- Read `guizang-ppt-skill/SKILL.md` before any rendering. Do not skip it.
- Pick every page's layout from the registered set in
  `references/layouts.md`. Do not invent layout classes.
- Preserve Guizang's animation hooks (`data-anim` / `data-animate`),
  Motion One loading, and the WebGL dual canvas where Style A applies.
- This prompt requires `guizang-ppt-skill` to be installed at
  `~/.agents/skills/guizang-ppt-skill/`. If it is not, the next agent
  must install it before rendering. The brief still ships.
- Run the validator above before reporting complete.
- Do not modify or post-process the rendered HTML in Humanize.
- The HTML that ends up on disk is produced by `guizang-ppt-skill`,
  not by Humanize.

## Inputs already produced by Humanize

- `deck_brief.md`
- `ast_outline.md`
- `slide_plan.json`
- `speaker_intent.md`
- `asset_manifest.md`
- `video_slots.json`
- `style_brief.md`

## Per-page media decisions (Humanize-owned)

- S01 马来西亚市场：线索全生命周期，不是客户管理 — image=gpt-photo
  - image.asset_path: `assets/s01-image.png`
  - image.prompt_hint: Slide title: 马来西亚市场：线索全生命周期，不是客户管理 | Slide message: 汇报人：于冰 Ivan · 海外经销商一部 · 日期 2026-08-13 | Page role: Open the deck. Set emotional anchor. | Asset guidance: Image: must be visually anchored, no Chinese text in the image (Chinese labels go in the slide layout).
- S02 开场：马来现在没有客户 — diagram=svg-html
  - diagram.asset_path: `assets/s02-diagram.svg`
  - diagram.prompt_hint: Slide title: 开场：马来现在没有客户 | Slide message: 62 条可跟进线索 | Page role: Establish common ground. Show system / scope. | Asset guidance: Diagram: render as inline SVG or HTML table, deterministic, no text overflow.
- S03 背景：线索从哪来，三类怎么分 — image=svg-html
  - image.asset_path: `assets/s03-image.svg`
  - image.prompt_hint: Slide title: 背景：线索从哪来，三类怎么分 | Slide message: 可跟进 62 = 手册 32 ∪ 7/23 获客净增 13 ∪ 金山过往名单净增 1 | Page role: Highlight the gap or contradiction. | Asset guidance: Image: must be visually anchored, no Chinese text in the image (Chinese labels go in the slide layout).
- S04 张力：录音在，不等于已经签 — diagram=svg-html, video=remotion-clip (10s)
  - diagram.asset_path: `assets/s04-diagram.svg`
  - diagram.prompt_hint: Slide title: 张力：录音在，不等于已经签 | Slide message: 可以证明：线索漏斗存在 | Page role: Walk through the process / decision tree. | Asset guidance: Diagram: render as inline SVG or HTML table, deterministic, no text overflow.
  - video.asset_path: `assets/s04-video.mp4`
  - video.prompt_hint: Slide title: 张力：录音在，不等于已经签 | Slide message: 可以证明：线索漏斗存在 | Page role: Walk through the process / decision tree. | Asset guidance: Short loop clip (8-12s), deterministic motion, no narration.
- S05 方法：按联系人升阶段，毕业才改口 — image=screenshot, diagram=svg-html, video=remotion-clip (8s)
  - image.asset_path: `assets/s05-image.png`
  - image.prompt_hint: Slide title: 方法：按联系人升阶段，毕业才改口 | Slide message: 一条逻辑线：池 → 事前调研 → 事中实际 → 当地难点 → 对方合作意愿 | Page role: Show evidence: real UI, screenshots, before/after. | Asset guidance: Image: must be visually anchored, no Chinese text in the image (Chinese labels go in the slide layout).
  - diagram.asset_path: `assets/s05-diagram.svg`
  - diagram.prompt_hint: Slide title: 方法：按联系人升阶段，毕业才改口 | Slide message: 一条逻辑线：池 → 事前调研 → 事中实际 → 当地难点 → 对方合作意愿 | Page role: Show evidence: real UI, screenshots, before/after. | Asset guidance: Diagram: render as inline SVG or HTML table, deterministic, no text overflow.
  - video.asset_path: `assets/s05-video.mp4`
  - video.prompt_hint: Slide title: 方法：按联系人升阶段，毕业才改口 | Slide message: 一条逻辑线：池 → 事前调研 → 事中实际 → 当地难点 → 对方合作意愿 | Page role: Show evidence: real UI, screenshots, before/after. | Asset guidance: Short loop clip (8-12s), deterministic motion, no narration.
- S06 证据：8 场录音、难点原文、对方口径 — image=svg-html
  - image.asset_path: `assets/s06-image.svg`
  - image.prompt_hint: Slide title: 证据：8 场录音、难点原文、对方口径 | Slide message: 8 场均可点开 | Page role: Close the deck. Reinforce the judgment. | Asset guidance: Image: must be visually anchored, no Chinese text in the image (Chinese labels go in the slide layout).
- S07 带走：漏斗位置，本周只推能升一级的 — image=svg-html
  - image.asset_path: `assets/s07-image.svg`
  - image.prompt_hint: Slide title: 带走：漏斗位置，本周只推能升一级的 | Slide message: 漏斗：S1 入库 52 不群发；S2 尽调 3 Delia / Valiram /  | Page role: Close the deck. Reinforce the judgment. | Asset guidance: Image: must be visually anchored, no Chinese text in the image (Chinese labels go in the slide layout).

## Media production (visual enhancement)

Each media slot above ships `asset_path` (where to write) and `prompt_hint`
(what to generate). Produce the asset, then reference it from the rendered
slide. Recommended generators (hot-pluggable — swap for any equivalent skill):

- **image** (`gpt-photo`): preferred — `baoyu-image-gen` driving the local
  Codex CLI (`--provider codex-cli`, uses the logged-in Codex/ChatGPT
  subscription, no `OPENAI_API_KEY` needed). Alternatives: `imagegen` /
  `imagen` / `nanobanana-ppt` (these need their own API key). Feed
  `prompt_hint`, honor `aspect_ratio` and `max_size_kb`, write to `asset_path`.
  Use synthesized images for atmospheric / conceptual / hero visuals; keep
  precise-text or data figures as deterministic SVG (image models garble
  exact labels and numbers).
- **image** (`screenshot`): capture the real UI / result; do not synthesize.
- **diagram** (`svg-html` / `html-table`): render as deterministic inline SVG
  or HTML from `prompt_hint`. No external call, no text overflow. This is the
  right choice for data, metrics, process steps, and any precise-label figure.
- **video** (`remotion-clip`): default to `remotion-video-production` (it
  orchestrates the pipeline) paired with `remotion-best-practices` (avoids
  unstable Remotion patterns — misused CSS/Tailwind animation, wrong asset
  paths); add `remotion-video-toolkit` only for complex work (captions,
  charts, 3D, batch templates). Build a deterministic loop of `duration_s`
  seconds (no narration), render to `asset_path` (mp4).
- **video** (`hyperframes`): use the HyperFrames pipeline for the clip.

Rule: an asset slot with `asset_path` is an executable task. A slot without
one is a label only — do not invent paths. Humanize decides *what* and
*where* (the per-page media plan); the downstream skill produces the file and
renders the deck. Humanize orchestrates the presentation; it does not own the
template that paints the final slide.

## Known-good checkpoint (read-only reference)

- `examples/03-codex-guizang-native-ink-classic/index.html`
  (Style A, Ink Classic, 10 slides, hero WebGL background, 86 `data-anim`
  occurrences). Open it to see the bar for Style A quality.

## Style A QA gates (must all pass)

- no `[必填]` template residue
- no `<!-- SLIDES_HERE -->` marker residue
- `canvas#bg-dark` exists
- `canvas#bg-light` exists
- `body.low-power` is not active by default
- `.slide.hero.light,.slide.hero.dark { background: transparent }` is applied so the WebGL hero canvas is visible
- meaningful `data-anim` / `data-animate` markers are present
- at least 3 `data-anim` occurrences per non-cover page (Ink Classic checkpoint has 86)

## Hand-off

The next agent writes its output to its own convention
(e.g. `outputs/guizang-rendered/index.html`). Do not write to
`outputs/guizang/` — that is reserved for legacy Humanize adapter paths
and is no longer used in v0.6.4.
