# Functional Spec: Standardized Event Page Template for SEO & Generative Search

**Prepared for:** Open Neuromorphic (ONM)
**Based on:** Audit of `set_1.txt` — 37 events across `student-talks`, `hacking-hours`, and `workshops`
**Scope note:** `community-resources` is excluded from this spec per direction — those pages are resource listings with an attached video, not talk recordings, and don't fit this template's shape.
**Purpose:** Define a template and generation process that turns raw transcript + front matter into a page structure that ranks well and gets cited well by generative search / AI answer engines, processable in small batches by a script.

---

## 1. What the audit found (and why it shapes this spec)

Before proposing a template, it's worth being explicit about what's actually in the source data, because a few things there change the design:

| Finding | Evidence | Implication for the spec |
|---|---|---|
| **Body copy quality is bimodal, not uniform.** Some entries already have structured "Key Themes" sections with pull-quotes (e.g. `kade-heckel-jax-pallas-optimization`, ~8.8K chars of existing markdown); others have **no body paragraph at all** — just front matter and a transcript (e.g. `evolutionary-optimization-neuromorphic-systems-catherine-schuman`). | Template can't assume it's "filling a gap" uniformly — for some pages it's augmenting, for others it's writing from scratch. The prompt/process needs to detect which case it's in rather than always regenerating from zero. |
| **Existing body copy and existing `description` fields were almost all written before the event happened, in invitation voice** — "join us for," "we're thrilled to have," future-tense framing of what an attendee "will learn." Every page in this dataset is now being read after the event, by someone searching or by a generative-search system indexing it, not by a prospective attendee deciding whether to show up. | **Presence and length are not sufficient tests for whether existing copy is usable as-is.** A lede or description can be well-written, complete, and still wrong for this page's actual audience because it's speaking to the wrong moment in time. The template needs a voice check — pre-event vs. post-event address — as a first-class test alongside the emptiness check, applied to both the body lede (§2.2) and the `description` field (§2.1). |
| **There is no reliable diarization anywhere in this dataset, including the entries with `>>` markers.** On closer inspection, `>>` marks *some* turn boundary but carries no speaker name, no consistent alternation pattern, and no way to distinguish host from guest from the marker alone — it can appear mid-sentence, continuing the same speaker's thought rather than switching speakers. Treating it as diarization overstates what's actually recoverable. **This is a permanent constraint, not a temporary gap** — there is no other transcription source (no raw auto-caption file, no diarized ASR output) available now or expected later; the `set_N.txt` transcript is the only transcription source that will ever exist for this content. | The template **cannot promise per-speaker attribution** anywhere, full stop — not as a "most entries" caveat, and not as something to revisit if better source material shows up later, but as a dataset-wide, permanent constraint. Any pull-quotes use generic attribution ("as discussed in the session," "the speaker noted") rather than naming who said what, unless a name is unambiguous from context (e.g. a single-author student talk with one clear voice). No schema field should imply per-speaker quote mapping is available by default. |
| **The `type` front-matter field is unreliable** — only 17 of 37 entries have it set; the rest must be inferred from folder path (`content/{workshops,hacking-hours}/...` vs. `content/neuromorphic-computing/student-talks/...`). | The script must derive category from **path**, not the `type:` field, and should backfill `type:` where it's missing as a side effect. |
| **Transcript richness is not evenly distributed**, though within scope this is now a minor issue — all 37 in-scope entries have rich transcripts (3,000+ words). The one near-empty transcript in the original sample (`sottosoglia-podcast`) was a `community-resources` entry, now out of scope. | The **fallback path for near-zero transcript signal (§2.5) is retained as a defensive measure** for future batches, but isn't a live concern in this sample now that `community-resources` is excluded. |
| **Front matter carries authoring scaffolding that must not leak into output** — HTML-comment-style annotations (`# Date of the student talk...`), and a `production_credits` block naming internal ops staff (event scheduling, social promotion, etc.) who are not speakers. | The extraction step must explicitly exclude comment-annotations and `production_credits` from any "people mentioned" or attribution logic — those names describe internal support roles, not talk content, and surfacing them publicly is a scope/appropriateness mismatch, not just noise. |
| **`aliases` (URL redirects) and `is_supporter` / `draft` flags exist and must survive untouched.** Breaking an alias 404s an already-indexed URL — actively counterproductive to an SEO goal. | Template output must be **additive to front matter, never a wholesale front-matter rewrite** — with one deliberate, scoped exception: `description` (§2.1) is fully rewritten rather than appended to, because it is the field most exposed to search snippets and generative-answer extraction, and invitation-voice copy performs poorly there. Every other existing key is preserved untouched. |
| **`software_tags` / `hardware_tags` are a real controlled vocabulary** (`faery`, `norse`, `spyx`, `snntorch`, `nengo`, `snp-by-innatera`), not free text. | This is a genuine internal-linking / topical-clustering lever for SEO. The template should **populate/validate tags against the existing vocabulary**, not invent new spellings, so tag hub pages stay coherent. |
| **`upcoming: true` appears on two entries that plainly already happened** (past dates, full transcripts with post-event dialogue). Stale flag, not real data. | Out of scope for content generation, but worth flagging: script should emit a warning/log line when `upcoming: true` co-occurs with a non-trivial transcript, so someone can correct the flag. Cheap to catch, meaningfully wrong if left. |

The short version: **the data is good enough to write from, but it's uneven** — variety in schema, variety in what's already been written, a systematic voice mismatch (invitation-era copy serving a post-event reader) that runs across nearly the whole set, and a hard constraint (no reliable speaker attribution, anywhere) that applies uniformly across the whole set rather than to a subset of it. A template that assumes clean, diarized inputs, or that assumes "present and well-written" is the same thing as "usable as-is," will produce misattributed quotes or stale-voiced copy across the board. Everything below is designed around that reality rather than the ideal case.

---

## 2. Template structure

One template, with conditional sections that activate based on what a given entry's inputs actually support — not separate templates per content type. The three in-scope content types (`student-talks`, `hacking-hours`, `workshops`) share the large majority of their structure; forking into fully separate templates would mean maintaining things that drift out of sync. Type-specific differences are handled as **section variants** within one structure.

### 2.1 Front matter (additive, with one scoped exception for `description`)

The script reads existing front matter, keeps every field it doesn't have an explicit job for, and adds/normalizes only these:

- **`type`** — set from folder path if absent or inconsistent with path.
- **`software_tags` / `hardware_tags`** — extract any project/vendor names mentioned in the transcript that match the *existing* controlled vocabulary; append (don't replace) if the page doesn't already list them.
- **`experience_tags` / `expertise_tags` / `field_of_application_tags`** — a second, separate controlled vocabulary, derived from user-applied Discord tags across the community, covering three independent facets:
  - `experience`: `student`, `researcher`, `industry`, `practitioner`, `beginner`, `intermediate`, `advanced`
  - `expertise`: `computer-vision`, `snn`, `machine-learning`, `digital-hardware`, `analog-hardware`, `software`, `robotics`, `materials`, `algorithms-learning`, `neuroscience`, `sensory`, `medicine`
  - `field-of-application`: `education`, `space`, `iot`, `automotive`, `consumer-electronics`, `environmental`, `medicine`, `defense`

  These are not extracted the same way as `software_tags`/`hardware_tags`. That vocabulary is literal — a transcript either mentions Faery or it doesn't. This vocabulary is mixed:
  - `field-of-application` is closer to literal: a talk about drone perception or medical imaging will generally name its application domain directly, so treat this the way `software_tags` are treated — look for the domain being named or unambiguously described in the transcript.
  - `experience` and `expertise` are editorial judgments, not literal mentions — a speaker doesn't say the word "intermediate" or "robotics" out loud as a self-tag. Infer these from what's covered and how technically the material is pitched (e.g. a talk assuming familiarity with SNN training dynamics and citing recent papers reads as `researcher`/`advanced`; a talk building up core concepts from scratch reads as `student`/`beginner`; a talk centered on hands-on tooling and workflow reads as `practitioner`). Apply the same "don't invent vocabulary" discipline as the existing tag rule — pick from the fixed lists above, don't coin new terms, and don't force a fit if none of the listed values clearly applies (it's fine to leave a facet with fewer tags than another entry, or to apply more than one value within a facet if the content genuinely spans levels or domains — e.g. a talk relevant to both `robotics` and `defense`).
  - Append to these fields the same way as `software_tags`/`hardware_tags` — don't replace existing values if the page already has some set.
- **`summary_points`** (new, optional) — 3–5 short bullet strings, the same content that drives the "Key Takeaways" section below. This gives generative-search crawlers and any future structured-data/FAQ schema a clean, quote-safe source, and doubles as the on-page bullet list so the same synthesis work is only done once. Skip it entirely on the empty-input fallback path (2.5).
- **A machine-readable flag when the fallback path was used** (e.g. `content_source: "resource-listing"` vs. `"talk-summary"`), so the fallback-path pages (§2.5) are distinguishable in the data from full-treatment pages, since they were built from front matter alone rather than a real transcript.
- **`description`** — rewritten in full, not appended to. This is the one deliberate exception to additive-only front matter, because `description` is the string most likely to be shown verbatim as a Google search snippet or lifted verbatim by a generative answer engine as the one-line summary of the page. Existing descriptions in this dataset were written as pre-event invitations and are, almost without exception, the wrong voice for a page now being read after the fact. The rewrite must satisfy all of the following:

  1. **The transcript is the primary source for every claim in the description — not the existing `description` field.** Mine the transcript itself for the mechanism, result, or comparison the new description will state. The existing description may be used as supplementary context (it can hint at what the talk covers, help disambiguate an ambiguous transcript passage, or confirm a name/term), but it is not a valid source for a claim on its own — it's frequently where the vague, topic-label framing this rewrite is meant to replace originally came from, so treating it as an equal source risks reproducing the same weak claim in new wording. The existing body copy is a separate matter and continues to be used as described in §2.2/§2.3.
  2. **Self-check every comparative or performance claim against the transcript before finalizing it.** Any claim of the form "outperforms X," "beats X," "achieves Y where prior approaches couldn't" is only permitted if you can point to a specific passage in the transcript that actually asserts it. Before writing such a claim into the description, re-read the transcript for that specific assertion. If you cannot locate a passage that supports it, do not include the claim — write a mechanism-and-outcome claim the transcript does support instead (per rule 3 below), rather than falling back to a vague topic label. This check happens as part of drafting, not as a flag for someone else to verify afterward.
  3. **Length ceiling: 150–160 characters, hard stop at 160.** This is the practical truncation point for Google's search snippet display; truncation mid-clause reads worse than a shorter, complete sentence. Treat this as a hard constraint to check per entry, not a rough target.
  4. **Mechanism and outcome over topic label.** State what was specifically shown or found, using the concrete nouns a domain-familiar reader would search for (named techniques, named hardware, named comparisons) — not just the subject of the talk. "Explores a talk about X" is a topic label and should be avoided; "Shows how X achieves Y using Z" is a mechanism-and-outcome claim and is the target shape.
  5. **No direct address to a prospective attendee.** Drop "join us," "discover how we," "you'll learn," and similar phrasing that assumes the reader is deciding whether to attend a future event. Write from the vantage point of someone who found this page after the fact — describe what the recording contains, not what a live audience will experience.
  6. **Fallback-path entries (§2.5) do not get a rewritten description that asserts talk content.** If there's no substantial transcript to draw from, the description should describe the page honestly (what the session was nominally about, per front matter) rather than manufacture a mechanism claim with nothing behind it. Strip attendee-address phrasing if present; don't invent a replacement claim. Log these entries as "description not rewritten — fallback path" per §2.1's fallback flag, so the reason a description is thin is machine-readable rather than looking like an oversight.

  **Worked example** (the standard to match):
  - Before: *"Join us for an insightful student talk on Embodied Visuomotor Representation by Levi Burner. Discover how we can embody the sense of distance/scale in a robot through its actions! and not rely on its calibration."*
  - After: *"Discover how Embodied Visuomotor Representation lets robots perform uncalibrated tasks like gap jumping using only internal action signals and time-to-contact."*
  - Why the "after" version is correct: no attendee-address; states the specific mechanism (internal action signals, time-to-contact) and specific outcome (uncalibrated gap jumping) rather than a vague topic label; the mechanism and outcome are drawn from the transcript itself, not carried over from the old description's vaguer "embody the sense of distance/scale" framing; under 160 characters.

Everything else — `date`, `author`, `video`, `image`, `aliases`, `draft`, `is_supporter`, `speaker_slides`, `speaker_code`, `production_credits`, etc. — passes through unmodified.

### 2.2 Page body — standard path (the normal case: transcript has real content)

```
[Existing lede paragraph: keep as-is only if it is both (a) substantial —
 not empty or thin — and (b) written in post-event voice, describing what
 was said or found rather than inviting attendance. If either condition
 fails, rewrite the lede rather than keeping it verbatim.

 Voice check (apply before the length check): a present, well-written lede
 can still fail this test, because most existing ledes in this dataset were
 authored as pre-event invitations. Signals that a lede is pre-event and
 should not be kept verbatim: direct address to a prospective attendee
 ("join us," "we're thrilled to have"), future-tense framing of what the
 audience "will learn/explore/discover," or content structured as an
 agenda for an upcoming session rather than a report of what happened.

 Don't discard a failing lede wholesale — extract first. A pre-event lede
 often contains real content worth keeping even though its framing fails
 the voice check: an agenda list, a named contest or dataset, a specific
 technical scope. Pull the concrete content into the rewritten lede or
 into Key Takeaways; discard only the invitation framing itself (the
 greeting, the "join us," the direct address to a live audience).]

## Key Takeaways
- [3-5 bullets, synthesized from transcript + existing body]
- Written as standalone factual claims, not "in this talk, X discusses..."
  framing — generative search engines lift bullets like this directly,
  and self-contained claims survive being lifted out of context.

## [Type-variant section — see 2.3]

## What This Means for [neuromorphic computing / the field]
- 1-2 short paragraphs connecting the specific talk content to the
  broader field context. This is the section most likely to differentiate
  ONM's page from a generic YouTube-description scrape, and it's the
  section most valuable for "why does this matter" style generative queries.

[Optional: 1-2 short pull-quotes, each under the copyright-safe length
 threshold. Attribute generically ("the speaker noted," "as discussed in
 the session") rather than to a named individual, unless the entry has a
 single unambiguous voice (e.g. a solo student talk) and context makes the
 attribution safe. Do not build quote attribution around the `>>` marker —
 it does not reliably indicate a speaker change.]

## Resources
- Links already present in front matter (speaker_slides, speaker_code,
  speaker_paper, speaker_notebook, website) rendered as a clean list —
  this exists in the data already, just needs surfacing consistently.
```

### 2.3 Type-variant section (swap based on path-derived `type`)

- **`student-talks`** → "About the Research" — grounded in `speaker_paper` + the published-work framing already common in this category's existing body copy (several entries already do this well, e.g. `learning-long-sequences-in-snns`; extend the pattern, don't replace it).
- **`hacking-hours`** → "What Was Built / Demonstrated" — practical, tool-focused; several entries already contain "Key Themes and Ideas" sections with code-adjacent pull-quotes (e.g. the Kade Heckel and Alexandre Marcireau entries) — when this exists, restructure/tighten it into the standard shape rather than discarding and rewriting.
- **`workshops`** → "Workshop Format & Takeaways" — slightly more agenda-oriented, since workshops in this dataset skew toward structured multi-part sessions (`start_time`/`end_time`/`time_zone` fields are workshop/student-talk-specific and imply a defined session shape worth reflecting).

### 2.4 Length target

Target **400–700 words of new/restructured body copy**, not counting front matter or existing untouched content. This is deliberately modest: the goal is a complete, well-structured summary that's genuinely useful and quote-safe, not a maximalist wall of text. Padding length doesn't improve generative-search performance — structure, factual density, and clean extractable claims do. (This word-count target does not apply to `description`, which has its own, much shorter, character-based ceiling per §2.1.)

### 2.5 Fallback path — near-zero transcript signal

Not a live concern in this sample (all 37 in-scope entries have rich transcripts) now that `community-resources` — home to the one near-empty example found in the original audit — is out of scope. Kept in the spec as a **defensive measure for future batches**, since nothing guarantees every future `student-talks`/`hacking-hours`/`workshops` entry will have a substantial transcript (a cancelled recording, a technical failure, a talk with no video at all).

Triggered when transcript word count falls below a low threshold (~500 words is a reasonable placeholder, pending a real example to calibrate against) **or** the transcript is clearly non-speech (e.g. only `[Music]`/`[Applause]` style tags).

On this path, the template drops the "Key Takeaways from a talk" framing (there's no talk content to take away) and instead produces a short, honest page built from front matter and any existing body copy only: what the session was about, who was involved, why it's relevant to the field. **No talk-summary content is fabricated to fill the gap** — this applies to `description` as much as to body copy; see §2.1, rule 6. This path sets the `content_source` flag (§2.1) so fallback-path pages are distinguishable in the data from full-transcript pages.

---

## 3. Processing script: best practices

You mentioned the script will process bundles of a few transcripts at a time rather than the full set at once — that's the right call for a task like this, and a few things are worth building in given what the audit surfaced:

1. **Parse category from folder path first, `type:` field second.** Don't trust `type:` alone — it's missing on more than half of entries in this sample.
2. **Detect "already has structured body content" vs. "empty/thin body" before generating**, and branch accordingly. Some entries need light restructuring of good existing prose; others need to be written from nothing. Treating both cases the same way either flattens good existing writing or fails to fill real gaps.
3. **Default to generic attribution for all pull-quotes.** Don't treat `>>` markers as a diarization signal — they mark turn boundaries inconsistently and don't reliably indicate a speaker change, let alone identify who's speaking. Only attribute a quote to a named individual when the entry has one unambiguous voice (e.g. a solo `student-talks` entry with a single `author`) and even then, prefer paraphrase over quotation where exact wording isn't load-bearing.
4. **Never surface `production_credits` names or inline front-matter comments as content.** These are structurally present in the source but are not talk content.
5. **Validate all four tag fields against their respective controlled vocabularies** before writing new values — never invent a spelling or a value outside the fixed lists. `software_tags`/`hardware_tags` are validated against the vocabulary already in use across published entries (e.g. `faery`, `norse`, `spyx`, `snntorch`, `nengo`, `snp-by-innatera`). `experience_tags`/`expertise_tags`/`field_of_application_tags` are validated against the site-wide Discord-derived index given in §2.1 — this one is a fixed, closed list, not something to extend by pattern-matching new terms from a transcript.
6. **Treat front matter as additive-only, except for `description` (§2.1), which is fully rewritten by design.** Diff against the original file and confirm no existing key was deleted or overwritten, and that the only field replaced outright rather than appended-to is `description` — this is the single highest-leverage safety check for the `aliases`/redirect risk.
7. **Log a warning (don't auto-fix) on `upcoming: true` + substantial transcript.** That's a content-correctness bug adjacent to this task, not part of it, but it's free to catch in the same pass.
8. **Batch by category where possible**, not just arbitrary chunks. Since the type-variant section (2.3) is the main place output shape differs, running same-type entries through together makes it much easier to spot-check consistency across a batch before moving to the next.
9. **Emit a per-batch log** (which entries hit the fallback path, which had existing structured content that got restructured vs. entries written from scratch, any tag/vocabulary mismatches, any stale-flag warnings) as a record of what happened in the batch.
10. **Apply the same sourcing discipline to `description` that applies to pull-quotes and Key Takeaways.** Since `description` is now actively rewritten rather than passed through, it needs the same "detect existing content vs. write fresh" branching logic as body copy (item 2), and the same fabrication guardrail as quotes (item 3): don't assert a comparative or mechanism claim in the description unless the transcript itself supports it (§2.1, rules 1–2) — the transcript is the source to check, not the paper or the old description.

---

## 4. Open questions worth settling before the first real batch

- Since the fallback path (§2.5) has no live example in-scope right now, it's untested against real data — worth deliberately holding onto one thin-transcript entry (even from `community-resources`, just to test the branch logic) before the first production run, rather than shipping it unverified.