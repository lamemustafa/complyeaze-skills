# Your broker statement probably states your capital gains twice

*29 July 2026. Every figure here comes from a file that was run, and can be
re-run.*

Filing an Indian income tax return is not hard because the tax is hard. It is
hard because the documents disagree with each other, and nothing tells you when.

I wrote a parser to read a Zerodha Tax P&L into Schedule CG. It worked on a
statement I had constructed from the documented format. Then I ran it on two
real ones.

It reported exactly double.

The captured output showed every parsed bucket at exactly twice the broker's
own summary, with no partial overlap or bucket-specific exception.

Every figure. Short-term gains, long-term gains, intraday, dividends — each one
precisely twice the broker's own summary. Not a rounding error, not a partial
overlap. A clean factor of two, which is the kind of wrong that looks like a bug
in your own arithmetic and is not.

## What the file actually contains

**A Zerodha workbook states the same realised gains twice, by design.**

The *Tradewise Exits* sheet gives every trade: 326 rows of short-term equity, 88
of long-term. The *Equity and Non Equity* sheet restates the same gains scrip by
scrip: 41 rows and 14 rows covering identical money.

Both are correct. Both are useful — one for detail, one for a per-scrip view.
Read them together and you have doubled the capital gains going onto the return,
and therefore roughly doubled the tax.

The parser was reading every sheet, because that is the obvious thing to do.

## The fix does not look at sheet names

Naming the sheets would work for Zerodha and fail for the next broker. So the
parser compares totals instead. When two views of one bucket agree within a
rupee, the detail view is counted and the restatement is reported by name. When
they disagree, both are kept and the filer is asked to resolve it, because a
disagreement means one of them is not a duplicate.

It then reconciles every bucket against the realised-profit breakdown the
statement prints about itself:

```
✓ 111A ties to the statement's own summary
✓ 112A ties to the statement's own summary
✓ speculative ties to the statement's own summary
```

A bucket that does not tie is a stop, not a rounding difference.

## Three more, from the same two files

**The *Open Positions* sheet was readable as gains.** Its header maps cleanly —
symbol, quantity, a profit column. But that profit is *unrealised*, sitting on
holdings still open at year end, and unrealised profit is not income at all. It
is skipped now, along with ledger balances and charge tables.

**The raw `Profit` column sits to the left of `Taxable Profit`.** First-match
wins takes the wrong one. On a holding bought before 31 January 2018 the second
column is the one carrying grandfathering under s.55(2)(ac), and the difference
between them is real money. Header candidates are now ranked by how specific the
match is, not by where the column happens to sit.

**Identical rows within one statement are ordinary.** The same scrip sold twice
at the same price on the same day is not a duplicate. Only the same row
appearing in two different statements is, and only that is flagged now.

## AIS does it too

The department's own Annual Information Statement lists dividend twice. Once
under `SFT-015`, reported by the registrar. Again under `TDS-194`, from the
company's own TDS return. The same money, two reporting channels.

The Taxpayer Information Summary deduplicates them. AIS does not.

That matters because TIS is a deduplicated roll-up of the AIS detail, which
makes it the strongest check available on the two documents: every TIS category
should equal the sum of its AIS information codes. The rebuilt synthetic TIS
regression fixture preserves five exact category totals without publishing the
live pair's figures.

| TIS category | AIS codes | Total |
|---|---|---|
| Dividend | `SFT-015` + `TDS-194K` | 4,280 |
| Interest, savings bank | `SFT-016(SB)` | 8,745 |
| PF withdrawal | `TDS-192A` | 5,43,210 |
| Sale of securities | `SFT-17-LES(M)` + `SFT-17-OTU(M)` | 8,76,540 |
| Purchase of securities | `SFT-17(Pur)` | 7,65,430 |

Adding the duplicate dividend source still overstates the deduplicated TIS row.
A category that does not tie is where a missed source hides.

## And one that will catch people all year

Form 168 is the successor to Form 26AS under the Income-tax Act 2025. It is
headed **Tax Year 2026-27**. An AY 2026-27 return covers **FY 2025-26**.

Those are different years. The TDS on the Form 168 you can download today
belongs to next year's return. The portal is running both modules concurrently,
which makes this easy to get wrong and hard to notice — the numbers look
entirely plausible in the wrong box.

## Why this is a parser and not a prompt

A language model reading a 400-row spreadsheet makes exactly these mistakes,
confidently, in fluent prose. It has no way to notice that two sheets are the
same money, and every explanation it offers for the resulting figure will sound
correct.

The arithmetic belongs to code that can be checked against a number the broker
itself printed. The engine's invented regression case computes ₹1,23,184.00
before s.288B and ₹1,230 payable after TDS, with every intermediate asserted.

Everything it cannot do to that standard, it refuses — a non-resident, a capital
loss needing set-off, land without an indexed cost, a mutual fund whose equity
orientation nobody has confirmed. Refusing is the feature. A tool that guesses
at tax is worse than no tool.

## The test suite that missed all of it

Worth saying plainly, because it is the more useful lesson.

Every one of these defects was live while the suite passed clean. It used
superset assertions — "these buckets exist" rather than "these buckets and no
others, with these totals" — and a date check that passed when no dates had been
parsed at all.

It now asserts exact figures, and each of the fixtures above exists because the
code once got it wrong.

---

Everything here is in
[complyeaze-skills](https://github.com/lamemustafa/complyeaze-skills):
Apache-2.0, no dependencies, `python3 script.py` on a clean machine.

Alpha. AY 2026-27, resident individuals, non-audit. It never touches the portal
and never handles credentials.

*General reference, not tax advice. Verify every figure against the source
before you file.*
