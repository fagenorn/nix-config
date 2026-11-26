# Audit of the console page, 25 November 2026

The owner's reading of the live desk page on 25 November 2026, with seven sprints running across three projects. Each row is something the page showed, with whether a layperson can tell from it what is happening (Happening), what waits on whom (Waits on) and why (Why). Later slices measure their before and after against this record, by [the plain-words rule](./write-for-the-owner.md) and [the glossary](./owner-words.md).

Yes means the page says it in plain words, No means it does not.

## What the page showed

| Surface | What it showed | Happening | Waits on | Why |
|---|---|---|---|---|
| Top statement | A count of how many things need the owner ("N things need you") | Yes | Yes | No |
| First card | A question about whether "the next contract binding added to nix-config" landed and activated with no manual switch, badged "AC3" and "holds 1 issue" | No | No | No |
| Capacity strip | "p1 out until Sat 10:00", with no word saying p1 is an account | No | Yes | No |
| Sprint grid | An unexplained grid of squares per sprint and a count such as "58 of 94" | No | No | No |
| Sprint now-line | "landing 3 of 94: <the sprint's own title>": a stage and a count, with the sprint's title again, not the work | No | No | No |
| Report fold | "Show the report" opens on the last exchange between the lead and the manager: hundreds of words about pull requests, commit ids, claims and the permission classifier | No | No | No |
| Report body | A column of bare issue numbers | No | No | No |
| Live-fault line | A 400-character run of test names and commit ids, with its Withdraw button glued to the end | No | No | No |
| Page length | 7,528 px tall with every fold closed, about 123,000 px with them open | No | No | No |
| Spend page | Money and token kinds; nothing about time | No | No | No |

## What the rows show

- The page counts what needs the owner well, and says almost nothing about what any sprint is doing.
- Internal names are never glossed: AC3, holds, landing, claims, the permission classifier, p1.
- Issue numbers, commit ids and test names are the subject of lines, where [the rule](./write-for-the-owner.md) puts them last and ADR-console-014 puts them behind a fold.
- A count is given without saying what it counts, and a line about now gives a stage, never the work.
- Folds open on the wrong thing, and the open page is too long to read.

## How a later slice uses this

Read the same surface on the live page, give each of Happening, Waits on and Why a Yes or a No by the same test (could someone who has never seen the repository say it after reading the line aloud), and compare with the row here.
