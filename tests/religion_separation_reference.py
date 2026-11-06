"""Independent literal classification and one bounded design preference."""

NAMES = (
    "catholic",
    "protestant",
    "orthodox",
    "oriental_orthodox",
    "sunni",
    "shiite",
    "ibadi",
    "jewish",
    "mahayana",
    "gelugpa",
    "theravada",
    "confucian",
    "hindu",
    "shinto",
    "sikh",
    "animist",
    "atheist",
)
HERITAGES = (
    frozenset(NAMES[:4]),
    frozenset(NAMES[4:7]),
    frozenset({"jewish"}),
    frozenset({"mahayana", "gelugpa", "theravada", "hindu", "sikh"}),
    frozenset({"confucian", "shinto"}),
    frozenset({"animist"}),
    frozenset({"atheist"}),
)
GROUPS = (
    frozenset(NAMES[:8]),
    frozenset({"mahayana", "gelugpa", "theravada", "hindu", "sikh", "confucian", "shinto"}),
    frozenset({"animist"}),
    frozenset({"atheist"}),
)


def category(state, observed):
    if state == observed:
        return "state"
    if any({state, observed} <= row for row in HERITAGES):
        return "heritage"
    if any({state, observed} <= row for row in GROUPS):
        return "group"
    return "other"


def score(*, state, law, need, protection, authority=300, crisis=False, ai=True):
    """Only explicit local design contributions; no acceptance/population forecast."""
    if not ai or law != "law_freedom_of_conscience":
        return 0
    result = 0
    if state in NAMES and state != "atheist":
        if need is True:
            result += 6
        if protection is not False:
            result -= 4
    # Existing same-consumer independent native authority-loss constraint.
    if authority is not None and authority < 100:
        result -= 8
    if crisis:
        result -= 10
    return result
