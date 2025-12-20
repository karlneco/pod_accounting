import os
import time

import requests
from datetime import date as _date
from decimal import Decimal, ROUND_HALF_UP
from ..models import db, ExchangeRate

API_KEY = os.getenv("EXCHANGERATE_HOST_KEY")

def usd_to_cad(amount: Decimal, on_date: _date) -> Decimal:
    """
    Convert a USD amount into CAD for the given date.
    - First tries to load a stored ExchangeRate (currency_code='USD') for on_date.
    - If none exists, fetches from exchangerate.host, stores it, and returns amount * rate.
    Returns a Decimal rounded to 2 places.
    """
    # 1) Look for a saved rate
    rate_obj = ExchangeRate.query.filter_by(currency_code='USD', date=on_date).first()
    if not rate_obj:
        # 2) Fetch from public API with retry logic
        url = f"https://api.exchangerate.host/historical?date={on_date.isoformat()}"
        params = {"base": "USD", "symbols": "CAD"}
        # include the key as a query-param if required
        if API_KEY:
            params["access_key"] = API_KEY

        max_retries = 3
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                raw_rate = data['quotes']['USDCAD']
                if raw_rate is None:
                    raise ValueError(f"No CAD rate returned for {on_date}")
                break
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) + 1
                        time.sleep(wait_time)
                        continue
                raise
        
        # 3) Persist it
        rate_obj = ExchangeRate(
            currency_code='USD',
            date=on_date,
            rate=Decimal(str(raw_rate))
        )
        db.session.add(rate_obj)
        db.session.commit()

    # 4) Compute and return
    cad = (amount * rate_obj.rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return cad
