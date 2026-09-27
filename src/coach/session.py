"""End-of-session scoreboard and the long-run progress trend, both read from SQLite."""

from . import store


def print_summary(mode: str) -> None:
    scores = store.session_scores()
    if not scores:
        return
    n = len(scores)

    def avg(key: str) -> float:
        return sum(s[key] for s in scores) / n

    print(f"\n📈 {n} answers this session ({mode})")
    print(
        f"   avg {avg('wpm'):.0f} wpm · {avg('fillers'):.1f} fillers/answer · "
        f"{avg('pauses'):.1f} pauses/answer · {avg('lead_in'):.1f}s to start talking"
    )


def print_trend(limit: int = 20) -> None:
    """The point of the whole exercise: watch fillers and lead-in fall over weeks."""
    rows = store.trend(limit)
    if not rows:
        print("No sessions recorded yet.")
        return
    print(
        f"\n{'Date':<17} {'Mode':<7} {'Answers':>7} {'WPM':>5} "
        f"{'Fillers':>8} {'Pauses':>7} {'Lead-in':>8}"
    )
    print("─" * 63)
    for r in rows:
        print(
            f"{r['started_at'][:16]:<17} {r['mode']:<7} {r['answers']:>7} "
            f"{r['wpm']:>5.0f} {r['fillers']:>8.1f} {r['pauses']:>7.1f} "
            f"{r['lead_in']:>7.1f}s"
        )
    first, last = rows[0], rows[-1]
    if len(rows) > 1:
        print("─" * 63)
        print(
            f"{'change':<17} {'':<7} {'':>7} "
            f"{last['wpm'] - first['wpm']:>+5.0f} "
            f"{last['fillers'] - first['fillers']:>+8.1f} "
            f"{last['pauses'] - first['pauses']:>+7.1f} "
            f"{last['lead_in'] - first['lead_in']:>+7.1f}s"
        )
        print("   (wpm up is good; fillers, pauses and lead-in down is good)")
