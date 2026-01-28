import os
import time

import requests
from datetime import date as _date, datetime as _datetime
from decimal import Decimal, ROUND_HALF_UP
from ..models import db, ExchangeRate

API_KEY = os.getenv("OPEN_EXCHANGE_API") or os.getenv("EXCHANGERATE_HOST_KEY")

def _normalize_date(on_date: _date | _datetime) -> _date:
    if isinstance(on_date, _datetime):
        return on_date.date()
    return on_date

def usd_to_cad(amount: Decimal, on_date: _date | _datetime) -> Decimal:
    """
    Convert a USD amount into CAD for the given date (or datetime).
    - First tries to load a stored ExchangeRate (currency_code='USD') for the date.
    - If none exists, fetches from Open Exchange Rates and stores it for that date.
    - If the provider doesn't have a rate for that specific date, fall back to the
      provider's latest (end-of-day-style) rate.
    Returns a Decimal rounded to 2 places.
    """
    on_day = _normalize_date(on_date)
    # 1) Look for a saved rate
    rate_obj = ExchangeRate.query.filter_by(currency_code='USD', date=on_day).first()
    if not rate_obj:
        if not API_KEY:
            raise ValueError("Missing OPEN_EXCHANGE_API key")

        # 2) Fetch from Open Exchange Rates with retry logic
        url = f"https://openexchangerates.org/api/historical/{on_day.isoformat()}.json"
        params = {"app_id": API_KEY, "symbols": "CAD"}

        max_retries = 3
        raw_rate = None
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                if data.get("error"):
                    raw_rate = None
                    break
                raw_rate = data.get("rates", {}).get("CAD")
                if raw_rate is None:
                    raise ValueError(f"No CAD rate returned for {on_day}")
                break
            except requests.exceptions.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) + 1
                        time.sleep(wait_time)
                        continue
                raw_rate = None
                break

        # 2b) Fall back to latest if historical is unavailable
        if raw_rate is None:
            resp = requests.get(
                "https://openexchangerates.org/api/latest.json",
                params=params,
                timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            raw_rate = data.get("rates", {}).get("CAD")
            if raw_rate is None:
                raise ValueError("No CAD rate returned from latest endpoint")

        # 3) Persist it
        rate_obj = ExchangeRate(
            currency_code='USD',
            date=on_day,
            rate=Decimal(str(raw_rate))
        )
        db.session.add(rate_obj)
        db.session.commit()

    # 4) Compute and return
    cad = (amount * rate_obj.rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return cad
