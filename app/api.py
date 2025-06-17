"""API route handlers."""

import asyncio

from fastapi import APIRouter

from app.logger import get_logger
from app.treasury import (
    BitcoinETFHoldings,
    extract_arkb_holdings,
    extract_bitb_holdings,
    extract_brrr_holdings,
    extract_btc_mini_holdings,
    extract_btcw_holdings,
    extract_defi_holdings,
    extract_ezbc_holdings,
    extract_fidelity_holdings,
    extract_gbtc_holdings,
    extract_hodl_holdings,
    extract_ibit_holdings,
)

logger = get_logger(__name__)
router = APIRouter()


@router.get("/get-daily-holdings")
async def test_screenshot():
    ETF_EXTRACTOR_FUNCS = [
        extract_ibit_holdings,
        extract_fidelity_holdings,
        extract_gbtc_holdings,
        extract_arkb_holdings,
        extract_btc_mini_holdings,
        extract_bitb_holdings,
        extract_hodl_holdings,
        extract_brrr_holdings,
        # extract_btco_holdings, # TODO - problem
        extract_ezbc_holdings,
        extract_btcw_holdings,
        extract_defi_holdings,
    ]

    async def run_all_extractors() -> list[BitcoinETFHoldings]:
        coroutines = [func() for func in ETF_EXTRACTOR_FUNCS]
        raw_results = await asyncio.gather(*coroutines, return_exceptions=True)
        results = []
        for func, result in zip(ETF_EXTRACTOR_FUNCS, raw_results):
            if isinstance(result, Exception):
                logger.warning("Extractor %s failed: %s", func.__name__, result)
            else:
                results.append(result)
        return results

    results = await run_all_extractors()
    return results
