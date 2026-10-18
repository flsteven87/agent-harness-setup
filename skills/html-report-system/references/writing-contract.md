# HTML Report Writing Contract

Use this contract for self-authored HTML reports that explain product, engineering, operating, or
strategy work. Format-specific contracts continue to own sections, visuals, evidence, and layout.

## Identity, thesis, summary

Keep three jobs separate:

1. **Identity** names the artifact. Put it in the browser `<title>` and the single `<h1>`. Use the
   user's requested report name when one is given. Otherwise use a stable subject plus document type.
   Add a date or window only when it distinguishes archived reports.
2. **Thesis** states what the current evidence changes. Place it immediately below the identity as a
   subtitle or executive headline. A new evidence cycle can change the thesis without renaming the
   report.
3. **Summary** explains the consequence, current availability, and supported decision in one short
   paragraph. The body supplies proof and qualifications.

The identity identifies. The thesis interprets. The summary explains.

Example:

| Layer | Copy |
|---|---|
| Identity | `我的 Sprint` |
| Thesis | `帳戶重複問題收斂後，批次匯入成為下一條產品主線` |
| Summary | `目前已完成優先序與 ownership 重整；產品結果仍待 merge、deployment 與 staging 驗證。` |

## Conversation boundary

Treat prompts, chat turns, consultations, and meeting notes as **intake evidence**. Extract the
subject, user-owned name, decision, constraint, rationale, and unresolved question. Write the report
so a reader who never saw the conversation can understand it.

Preserve a user's exact wording when it defines the artifact name, an approved product term, a
decision, or a material constraint. Attribute or quote a conversation only when who said the words
or the exact words changes the evidence. Put that material beside the supported claim or in the
evidence appendix.

Convert conversational framing into durable report language:

| Intake wording | Report wording |
|---|---|
| `我們要接手前任團隊的工作` | `既有工作已轉入目前團隊的執行佇列` |
| `產品負責人接下來會忙商務合作` | `工程責任已調整，以保留商務合作容量` |
| `你剛才建議先收 bug` | `本期順序：先完成 P0 bug gate，再投入 P1 產品主線` |

## Acceptance

Accept the writing only when:

- the `<h1>` still identifies the same report after the current conclusion changes;
- the thesis can change without forcing an artifact rename;
- the summary states consequence and current state without requiring chat history;
- first-person or agent-process language appears only when attribution is evidence;
- the report does not present a prompt, response, or handoff chronology as the product story.
