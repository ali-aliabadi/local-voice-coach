"""The startup tree: pick a mode, then pick who plays the interviewer.

Skipped entirely when --mode and --model are both given, so daily practice never has to
navigate a menu.
"""

from . import backends, store


def _box(title: str, lines: list[str]) -> None:
    width = max([len(line) for line in lines] + [len(title) + 4])
    print(f"\n┌─ {title} " + "─" * (width - len(title) - 3))
    for line in lines:
        print(f"│ {line}")
    print("└" + "─" * (width + 1))


def _ask(prompt: str, valid: dict, default: str):
    """Re-prompt until the answer is one of `valid`. Enter takes the default."""
    while True:
        try:
            choice = input(f"{prompt} [{default}]: ").strip() or default
        except EOFError:
            return valid[default]
        if choice in valid:
            return valid[choice]
        print(f"  pick one of: {', '.join(k for k in valid if not k.isdigit())}")


def choose_mode(modes: dict, default: str = "talk") -> str:
    order = sorted(modes)
    width = max(len(name) for name in order)
    valid, lines = {}, []
    for i, name in enumerate(order, 1):
        valid[str(i)] = valid[name] = name
        star = "*" if name == default else " "
        lines.append(f"{i}{star} {name:<{width}}  {modes[name].HELP}")
    _box("Mode", lines)
    return _ask("Mode", valid, str(order.index(default) + 1))


def choose_backend(role: str, mode_name: str) -> backends.Backend:
    """Show every backend that can play this role, mark what is reachable, and pick one."""
    rows, any_available = backends.survey(role)
    if not any_available:
        raise SystemExit(
            "\nNothing available: no internet, and LM Studio isn't serving a usable model.\n"
            "Start LM Studio (or reconnect) and try again."
        )

    # Measured beats published: once a backend has been used, show its real average.
    seen = store.measured_latency()
    real = {
        b.key: (f"{seen[b.key][0] / 1000:.1f}s n={seen[b.key][1]}" if b.key in seen else "—")
        for b, _ in rows
    }

    label_w = max(len(b.label) for b, _ in rows)
    lat_w = max(len(b.latency) for b, _ in rows)
    real_w = max([len(v) for v in real.values()] + [len("Yours")])
    cost_w = max(len(b.cost) for b, _ in rows)

    header = (
        f"#   {'Backend':<{label_w}}  {'Latency':<{lat_w}}  {'Yours':<{real_w}}  "
        f"{'Cost':<{cost_w}}  Free  {'RAM':<6}  Notes"
    )
    lines, valid, default, number = [header], {}, None, 0
    for backend, blocked in rows:
        if blocked:
            tag = "-  "
        else:
            number += 1
            tag = f"{number}  "
            valid[str(number)] = valid[backend.key] = backend
            default = default or str(number)
        lines.append(
            f"{tag} {backend.label:<{label_w}}  {backend.latency:<{lat_w}}  "
            f"{real[backend.key]:<{real_w}}  {backend.cost:<{cost_w}}  "
            f"{'yes ' if backend.free else 'no  '}  {backend.ram:<6}  "
            + (f"({blocked})" if blocked else backend.note)
        )
    _box(f"Interviewer for '{mode_name}'", lines)
    print(
        "  '-' rows are unreachable now. 'Latency' is published/estimated; "
        "'Yours' is measured\n  from your own sessions and is the number to trust.\n"
    )
    return _ask("Interviewer", valid, default)
