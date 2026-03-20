from __future__ import annotations

from datetime import datetime


def is_quiet_hour_local(
    *,
    start_hour: int | None,
    end_hour: int | None,
    now: datetime | None = None,
) -> bool:
    """Тихие часы по локальному часу сервера. Диапазон может переходить через полночь (напр. 22–8)."""
    if start_hour is None or end_hour is None:
        return False
    h = (now or datetime.now()).hour
    if start_hour == end_hour:
        return False
    if start_hour < end_hour:
        return start_hour <= h < end_hour
    return h >= start_hour or h < end_hour
