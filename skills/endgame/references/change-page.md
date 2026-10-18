# Change page

A change page rebuilds the user's mental model of one topic after a change moved it. It serves the
user's understanding; the code, tests, and checks remain the proof. Engagement is what preserves
understanding, so the page invites a prediction instead of asking to be read passively.

## 1. Resolve the page

One page per topic (a flow, subsystem, or product area), updated in place so it always describes the
current model. The destination follows `html-report-system`'s output policy. When the repository
assigns change pages no path, ask once with a recommended path inside the repository, then record
the answer in the repository's documentation policy so later runs reuse it. Done when the page's
absolute path is known and both runtimes can write it: a path inside the repository, never its Git
directory or a home-folder location.

## 2. Write it

Write in the user's words, following `html-report-system`'s writing contract. From the top:

1. **What changed and why:** the thesis and summary. The user should be able to retell the change
   from these lines alone.
2. **Open decisions**, if any, in the profile's pause format: one at a time, recommended option
   marked.
3. **One diagram**, when the changed behavior has a flow worth seeing: before and after, drawn as
   inline SVG. Draw each relation from the before and after code and tests, checked this turn,
   including unchanged callers, configuration, or external systems that decide the outcome. Cite
   `path:line` as text, linked to a pinned-revision URL when the repository has a remote.
4. **Terms** the page still needs, each in one plain sentence.
5. **Prediction** (optional): one closed `<details>` asking what happens in a named case, the answer
   inside.
6. **Footer:** the code revision explained (`base..head` of the code change) and what was not
   verified.

Done when every sentence and every drawn relation traces to code or a check read this turn.

## 3. Gate and hand over

Run the `html-report-system` rendering gate once after the last edit. Commit the page with the change
it explains, after the applicable review findings have landed so the page describes the final code. Put the
page's absolute path and `open <path>` in the close. Done when the gate is clean and the page is in the
endpoint's commit.
