from datetime import date, timedelta

def get_date_range(range_key: str, start: date=None, end: date=None):
    today = date.today()
    # default fallback
    if range_key == 'today':
        return today, today
    elif range_key == 'yesterday':
        d = today - timedelta(days=1)
        return d, d
    elif range_key == 'this_week':
        # assuming week starts Monday
        start_of = today - timedelta(days=today.weekday())
        return start_of, today
    elif range_key == 'last_week':
        start_of = today - timedelta(days=today.weekday() + 7)
        end_of   = start_of + timedelta(days=6)
        return start_of, end_of
    elif range_key == 'this_month':
        return today.replace(day=1), today
    elif range_key == 'last_month':
        first_this = today.replace(day=1)
        last_month_end = first_this - timedelta(days=1)
        return last_month_end.replace(day=1), last_month_end
    elif range_key == 'this_quarter':
        q = (today.month - 1)//3
        start_month = q*3 + 1
        return date(today.year, start_month, 1), today
    elif range_key == 'last_quarter':
        q = (today.month - 1)//3
        # back up one quarter
        end_month = (q*3) or 12
        end_year  = today.year if q else today.year-1
        start_month = end_month-2
        return date(end_year, start_month, 1), date(end_year, end_month, 1) + timedelta(days=31)
    elif range_key == 'this_year':
        return date(today.year, 1, 1), today
    elif range_key == 'last_year':
        return date(today.year-1, 1, 1), date(today.year-1, 12, 31)
    elif range_key == 'year_to_date':
        return date(today.year, 1, 1), today
    elif range_key == 'custom' and start and end:
        return start, end
    # fallback: all time
    return None, None
