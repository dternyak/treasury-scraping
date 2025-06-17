import asyncio
from typing import Callable, Awaitable, Union
from fastapi import APIRouter

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

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


# Custom exception for missing bitcoin quantity
class MissingBitcoinQuantityError(Exception):
    """Raised when bitcoin_quantity is None or data_found is False"""
    pass


# Type alias for extractor functions
ExtractorFunction = Callable[[], Awaitable[BitcoinETFHoldings]]


def create_retry_extractor(
    extractor_func: ExtractorFunction,
    max_attempts: int = 3
) -> ExtractorFunction:
    """Create a retry-enabled version of an extractor function"""

    @retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(MissingBitcoinQuantityError),
        reraise=True
    )
    async def retry_wrapper() -> BitcoinETFHoldings:
        try:
            result = await extractor_func()

            # Validate the result
            if not result.data_found or result.bitcoin_quantity is None:
                logger.warning(
                    f"No bitcoin quantity found for {result.etf_symbol}, "
                    f"data_found={result.data_found}, bitcoin_quantity={result.bitcoin_quantity}"
                )
                raise MissingBitcoinQuantityError(
                    f"Missing bitcoin quantity for {result.etf_symbol}"
                )

            logger.info(f"Successfully extracted {result.bitcoin_quantity} BTC for {result.etf_symbol}")
            return result

        except MissingBitcoinQuantityError:
            # Re-raise validation errors for retry
            raise
        except Exception as e:
            logger.error(f"Error in {extractor_func.__name__}: {e}")
            # Convert other exceptions to validation errors for retry
            raise MissingBitcoinQuantityError(f"Extraction failed: {str(e)}") from e

    # Preserve the original function name for logging
    retry_wrapper.__name__ = f"{extractor_func.__name__}_with_retry"
    return retry_wrapper


# Create retry-enabled versions of all extractors
extract_ibit_holdings_with_retry = create_retry_extractor(extract_ibit_holdings)
extract_fidelity_holdings_with_retry = create_retry_extractor(extract_fidelity_holdings)
extract_gbtc_holdings_with_retry = create_retry_extractor(extract_gbtc_holdings)
extract_arkb_holdings_with_retry = create_retry_extractor(extract_arkb_holdings)
extract_btc_mini_holdings_with_retry = create_retry_extractor(extract_btc_mini_holdings)
extract_bitb_holdings_with_retry = create_retry_extractor(extract_bitb_holdings)
extract_hodl_holdings_with_retry = create_retry_extractor(extract_hodl_holdings)
extract_brrr_holdings_with_retry = create_retry_extractor(extract_brrr_holdings)
extract_ezbc_holdings_with_retry = create_retry_extractor(extract_ezbc_holdings)
extract_btcw_holdings_with_retry = create_retry_extractor(extract_btcw_holdings)
extract_defi_holdings_with_retry = create_retry_extractor(extract_defi_holdings)


@router.get("/get-daily-holdings")
async def get_daily_holdings() -> list[BitcoinETFHoldings]:
    """Get daily holdings for all Bitcoin ETFs with retry logic"""

    extractors: list[ExtractorFunction] = [
        extract_ibit_holdings_with_retry,
        extract_fidelity_holdings_with_retry,
        extract_gbtc_holdings_with_retry,
        extract_arkb_holdings_with_retry,
        extract_btc_mini_holdings_with_retry,
        extract_bitb_holdings_with_retry,
        extract_hodl_holdings_with_retry,
        extract_brrr_holdings_with_retry,
        extract_ezbc_holdings_with_retry,
        extract_btcw_holdings_with_retry,
        extract_defi_holdings_with_retry,
    ]

    async def run_all_extractors() -> list[BitcoinETFHoldings]:
        coroutines = [func() for func in extractors]
        raw_results = await asyncio.gather(*coroutines, return_exceptions=True)
        results: list[BitcoinETFHoldings] = []

        for func, result in zip(extractors, raw_results):
            if isinstance(result, Exception):
                logger.error("Extractor %s failed after retries: %s", func.__name__, result)
                # Create a failed result object
                failed_result = BitcoinETFHoldings(
                    etf_symbol=func.__name__.replace("extract_", "").replace("_holdings_with_retry", "").upper(),
                    etf_name="Failed to extract",
                    website_url="",
                    bitcoin_quantity=None,
                    bitcoin_quantity_unit="BTC",
                    total_net_assets=None,
                    as_of_date=None,
                    data_found=False,
                    notes=f"Failed after retries: {str(result)}"
                )
                results.append(failed_result)
            else:
                assert isinstance(result, BitcoinETFHoldings)
                results.append(result)

        return results

    results = await run_all_extractors()

    # Log summary
    successful_extractions = sum(1 for r in results if r.data_found and r.bitcoin_quantity is not None)
    logger.info(f"Successfully extracted data for {successful_extractions}/{len(results)} ETFs")

    return results
