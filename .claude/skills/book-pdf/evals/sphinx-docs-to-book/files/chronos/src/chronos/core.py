"""Schedules: rules that generate datetimes."""
from datetime import datetime, timedelta


class Schedule:
    """A rule that generates the moments an event happens.

    Args:
        rule: A function that maps a datetime to the next occurrence after it.
        tz: Optional time zone for the occurrences.
    """

    def __init__(self, rule, tz=None):
        self.rule = rule
        self.tz = tz
        self._excluded = set()

    @classmethod
    def parse(cls, phrase: str, tz=None) -> "Schedule":
        """Build a schedule from an English phrase.

        :param phrase: For example ``"every weekday at 09:30"``.
        :param tz: A :class:`zoneinfo.ZoneInfo`, or ``None`` for naive times.
        :returns: The schedule the phrase describes.
        :raises ValueError: If the phrase is not understood.
        """
        raise NotImplementedError

    def upcoming(self, start: datetime, count: int = 1):
        """The next ``count`` occurrences after ``start``.

        Args:
            start: The moment to count from (excluded).
            count: How many occurrences to return.

        Returns:
            A list of datetimes in increasing order.
        """
        out, t = [], start
        while len(out) < count:
            t = self.rule(t)
            if t.date() not in self._excluded:
                out.append(t)
        return out

    def excluding(self, dates) -> "Schedule":
        """A copy of this schedule that skips the given dates."""
        s = Schedule(self.rule, self.tz)
        s._excluded = set(self._excluded) | set(dates)
        return s


def every(days=None, weekday=None, monthday=None, nth=None) -> Schedule:
    """Build a schedule from its parts.

    Args:
        days: Repeat every this many days.
        weekday: 0 for Monday ... 6 for Sunday.
        monthday: Day of the month; negative counts from the end.
        nth: With ``weekday``, the n-th such weekday of the month.

    Returns:
        A :class:`Schedule`.
    """
    def rule(t):
        return t + timedelta(days=days or 1)
    return Schedule(rule)
