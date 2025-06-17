import re
from textwrap import dedent
from typing import Any, Optional, cast

import markdown2
from bs4 import BeautifulSoup, Tag
from pydantic import BaseModel, Field

from app.firecrawl import screenshot
from app.gemini import call_gemini
from app.logger import get_logger

logger = get_logger(__name__)

class BitcoinETFHoldings(BaseModel):
    etf_symbol: str
    etf_name: str
    website_url: str
    bitcoin_quantity: Optional[float]  # Number of Bitcoin held
    bitcoin_quantity_unit: str  # "BTC" or "Bitcoin" etc.
    total_net_assets: Optional[str]  # Total fund value if visible
    as_of_date: Optional[str]  # Date of the holdings data
    data_found: bool  # Whether Bitcoin holdings data was successfully extracted
    notes: Optional[str]  # Any additional relevant information



class HoldingInfoSelector(BaseModel):
    """A model to hold the CSS selector for the relevant holdings information."""
    selector: str = Field(description="The most specific CSS selector for the element containing the holdings information.")
    reason: str = Field(description="A brief explanation of why this selector was chosen.")



async def find_best_selector_for_bitcoin_holdings(
    screenshot_url: str,
    preprocessed_dom: str,
    etf_symbol: str,
) -> HoldingInfoSelector:
    logger.info(
        "Finding best selector for %s using AI and preprocessed DOM.", etf_symbol
    )

    prompt = dedent(f"""
        Analyze the screenshot and the accompanying simplified HTML DOM for the {etf_symbol} ETF website.
        Your primary goal is to identify a WORKING CSS selector that isolates the main container
        (e.g., a <div>, <table>, or <section>) displaying the Bitcoin-holdings data.

        The selector MUST be effective and as simple as possible.

        Prioritize these types of selectors for simplicity and robustness:
        1. An `id` attribute if a relevant one is available (e.g., `#fundHoldingsTable`).
        2. A single, distinctive class name that seems unique to the holdings section (e.g., `.bitcoin-data-container`).
        3. A `data-*` attribute (e.g., `[data-testid="holdings-summary"]` or `[data-block-name="fund-details"]`).
        4. A clear and stable tag and class combination if the above are not suitable (e.g., `table.summary-table` or `div.fund-overview-section`).

        Avoid these pitfalls:
        * Overly complex selectors: Do NOT use many chained classes, multiple chained pseudo-classes (like `:nth-of-type(N)` or `:nth-child(N)`), or deep descendant combinators (e.g., `div > div > section > div > div.someClass`).
        * Relying on auto-generated or generic class names if more specific ones are available (e.g., avoid `.col-md-6` if there's also `.holdings-info`).
        * Selectors that are too general and could match multiple parts of the page.

        The selector needs to pinpoint the specific area containing the Bitcoin holdings data as seen in the screenshot.
        The provided HTML has been pre-processed. Focus on the structural tags that best match the visual data block in the screenshot.

        Simplified HTML DOM:
        ```html
        {preprocessed_dom}
        ```
    """).strip()

    selector_result: HoldingInfoSelector = await call_gemini(
        prompt=prompt,
        pydantic_model=HoldingInfoSelector,
        temperature=0.0,
        images=[screenshot_url],
    )

    logger.info(
        "AI identified selector for %s: '%s'. Reason: %s",
        etf_symbol,
        selector_result.selector,
        selector_result.reason,
    )

    return selector_result

def preprocess_html_for_analysis(html_content: str) -> str:
    soup = BeautifulSoup(html_content, "html.parser")

    body_element = soup.find("body")

    element_to_clean = cast(Tag, body_element if body_element else soup)

    # Now, `element_to_clean` is correctly typed as `Tag`, so this call is valid.
    for tag in element_to_clean.find_all(["script", "style", "svg"]):
        tag.decompose()

    return str(element_to_clean.prettify())

async def screenshot_and_extract_bitcoin_holdings(
    url: str,
    etf_symbol: str,
    special_instructions: Optional[str] = None,
    initial_actions: Optional[list[Any]] = None,
) -> "BitcoinETFHoldings":
    """
    Extracts Bitcoin ETF holdings via a robust, token-efficient, multi-stage AI process.
    """
    logger.info("[1/3] Fetching initial page content for %s from %s", etf_symbol, url)
    page_content = await screenshot(url, include_dom=True, initial_actions=initial_actions)

    logger.info("[2/3] Preprocessing DOM for %s to reduce token usage", etf_symbol)
    preprocessed_dom = preprocess_html_for_analysis(page_content.dom)

    logger.info("[2/3] Identifying best data selector for %s", etf_symbol)
    selector_result = await find_best_selector_for_bitcoin_holdings(
        screenshot_url=page_content.screenshot_url,
        preprocessed_dom=preprocessed_dom,
        etf_symbol=etf_symbol,
    )

    logger.info("[3/3] Executing focused scrape for selector '%s'", selector_result.selector)
    focused_content = await screenshot(url, selector=selector_result.selector, initial_actions=initial_actions)

    def extract_element_by_selector(html: str, selector: str) -> str:
        soup = BeautifulSoup(html, "html.parser")
        selected_element = soup.select_one(selector)
        return str(selected_element) if selected_element else ""

    selected_html = extract_element_by_selector(page_content.dom, selector_result.selector)
    focused_markdown = markdown2.markdown(selected_html)
    # logger.info("focused_markdown: %s", focused_markdown)

    special_note = f"\n\nSpecial instructions: {special_instructions}" if special_instructions else ""
    extraction_prompt = dedent(
        f"""
        Analyze the focused screenshot from the {etf_symbol} ETF website and the focused markdown content.

        {focused_markdown}

        website_url: {url}

        **Your task**: From this focused context, extract the data fields for the BitcoinETFHoldings model.

        etf_symbol: str
        etf_name: str
        website_url: str
        bitcoin_quantity: Optional[float]  # Number of Bitcoin held
        bitcoin_quantity_unit: str  # "BTC" or "Bitcoin" etc.
        total_net_assets: Optional[str]  # Total fund value if visible
        as_of_date: Optional[str]  # Date of the holdings data
        data_found: bool  # Whether Bitcoin holdings data was successfully extracted
        notes: Optional[str]

        {special_note}
        """
    ).strip()

    holdings: BitcoinETFHoldings = await call_gemini(
        prompt=extraction_prompt,
        pydantic_model=BitcoinETFHoldings,
        temperature=0.2,
        images=[focused_content.screenshot_url],
    )
    return holdings

# Individual ETF extraction functions
async def extract_ibit_holdings() -> BitcoinETFHoldings:
    """iShares Bitcoin Trust (IBIT)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://www.ishares.com/us/products/333011/ishares-bitcoin-trust",
        etf_symbol="IBIT"
    )


def get_daily_params_from_dom(dom: str) -> dict:
    """
    Parses the static DOM to find the parameters for the 'Daily Holdings' tab
    by looking inside its onclick attribute.
    """
    soup = BeautifulSoup(dom, "html.parser")
    # Find the table cell (td) for the Daily Holdings tab
    daly_tab_td = soup.find('a', id='DALYTab').find_parent('td')

    if not daly_tab_td:
        raise ValueError("Could not find the 'Daily Holdings' tab TD element in the DOM.")

    onclick_attr = daly_tab_td.get('onclick', '')

    # Use regex to find all the string arguments passed to getDocumentMenu
    # Example: getDocumentMenu('Fidelity','MFL','DALY', 'application/pdf', ...)
    params = re.findall(r"\'(.*?)\'", onclick_attr)

    if len(params) < 15:
        raise ValueError("Could not parse enough parameters from the onclick attribute.")

    # Map params based on their position in the getDocumentMenu function call
    return {
        'clientId': params[0],
        'applicationId': params[1],
        'docType': params[2],
        'docFormat': params[3],
        'securityId': params[4],
        'securityIdType': params[5],
        'collectionId': params[6],
        'criticalIndicator': params[12],
        'pdfDocName': params[14]
    }




async def extract_fidelity_holdings() -> BitcoinETFHoldings:
    """
    Fidelity Wise Origin Bitcoin Fund (FBTC) extraction.
    Dynamically constructs the Daily Holdings PDF URL from the page.
    """
    base_url = "https://www.actionsxchangerepository.fidelity.com/ShowDocument/ComplianceEnvelope.htm?_fax=-18%2342%23-61%23-110%23114%2378%23117%2320%23-1%2396%2339%23-62%23-21%2386%23-100%2337%2316%2335%23-68%2391%23-66%2354%23103%23-16%2369%23-30%2358%23-20%2376%23-84%23-11%23-87%230%23-50%23-20%23-92%23-98%23-116%23-28%2358%23-38%23-43%23-39%23-42%23-96%23-88%2388%23-45%23105%23-76%2367%23125%23123%23-122%23-5%2319%23-74%235%23-89%23-105%23-67%23126%2377%23-126%23100%2345%23-44%23-73%23-15%238%23-21%23-37%23-17%23-14%23-98%23123%23-18%2345%23-59%23-82%2367%2383%23112%2317%2370%23-78%2378%23-50%2336%23-86%23-90%2381%23-21%23-119%23-30%23120%2349%2328%23-98%2333%2351%23-78%23-119%23-16%2350%23-58%2350%23102%2348%23-17%2352%23-99%23"
    #
    # # First, get the page content with DOM
    # page_content = await scrape(
    #     url=base_url,
    #     response_format="rawHtml"
    # )
    #
    # # Extract Daily Holdings parameters from the onclick handler
    # daily_params = extract_daily_holdings_params(page_content.content)
    #
    # if not daily_params:
    #     raise ValueError("Could not extract Daily Holdings parameters from page")

    # Construct the PDF viewer URL
    # pdf_url = f"https://www.actionsxchangerepository.fidelity.com/ShowDocument/documentPDF.htm?{daily_params['query_string']}"

    # logger.info(f"Constructed Daily Holdings PDF URL: {pdf_url}")
    code = """
        function openDailyHoldings() {
      const dailyLink = document.getElementById('DALYTab');
      if (!dailyLink) return;

      // the click handler lives on the surrounding <td class="tdborder">
      const triggerCell = dailyLink.closest('td.tdborder');
      if (triggerCell) triggerCell.click();
    }

    /* run immediately -- or wrap in a load listener if needed */
    openDailyHoldings();
"""



    # Now screenshot the PDF viewer
    result = await screenshot(
        url=base_url,
        full_page=False,
        include_dom=False,
        initial_actions=[
            {"type": "wait", "milliseconds": 5000},  # Wait for PDF to load
            {"type": "executeJavascript", "script": code},
            {"type": "wait", "milliseconds": 15000},
            {"type": "screenshot"},
        ]
    )

    # logger.info(f"Screenshot result: {result}")

    # Extract holdings data from the screenshot
    custom_prompt = (
        "You are looking at a screenshot of the Fidelity Wise Origin Bitcoin Fund (FBTC) Daily Holdings Report PDF. "
        "This PDF contains the daily holdings information for the Bitcoin ETF.\n\n"
        "Extract the following fields for the BitcoinETFHoldings model:\n"
        "• etf_symbol: 'FBTC'\n"
        "• etf_name: 'Fidelity Wise Origin Bitcoin Fund'\n"
        "• bitcoin_quantity: (number of Bitcoin held, should be shown in the PDF)\n"
        "• total_net_assets: (total fund value in USD)\n"
        "• as_of_date: (the date these holdings are reported for)\n"
        "• notes: any additional relevant information\n\n"
        "The holdings data is typically shown in a table format within the PDF."
    )

    holdings = await call_gemini(
        prompt=custom_prompt,
        pydantic_model=BitcoinETFHoldings,
        temperature=0.1,
        images=[result.screenshot_url],
    )

    return holdings


async def extract_gbtc_holdings() -> BitcoinETFHoldings:
    """Grayscale Bitcoin Trust (GBTC)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://etfs.grayscale.com/gbtc",
        etf_symbol="GBTC"
    )

async def extract_arkb_holdings() -> BitcoinETFHoldings:
    """ARK 21Shares Bitcoin ETF (ARKB)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://data.chain.link/feeds/base/base/arkb-reserves",
        etf_symbol="ARKB"
    )

async def extract_btc_mini_holdings() -> BitcoinETFHoldings:
    """Grayscale Bitcoin Mini Trust (BTC)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://etfs.grayscale.com/btc",
        etf_symbol="BTC"
    )

async def extract_bitb_holdings() -> BitcoinETFHoldings:
    """Bitwise Bitcoin ETF (BITB)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://bitbetf.com/",
        etf_symbol="BITB"
    )

async def extract_hodl_holdings() -> BitcoinETFHoldings:
    """VanEck Bitcoin Trust (HODL)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://www.vaneck.com/us/en/investments/bitcoin-etf-hodl/overview/",
        etf_symbol="HODL"
    )

async def extract_brrr_holdings() -> BitcoinETFHoldings:
    """Valkyrie Bitcoin Fund (BRRR)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://coinshares.com/us/etf/brrr/",
        etf_symbol="BRRR"
    )

async def extract_btco_holdings() -> BitcoinETFHoldings:
    """Invesco Galaxy Bitcoin ETF (BTCO)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://www.invesco.com/us/financial-products/etfs/holdings?audienceType=Investor&ticker=BTCO",
        etf_symbol="BTCO",
        special_instructions="This page is supposed to show holdings but may not display them. Note if holdings are not visible."
    )

async def extract_ezbc_holdings() -> BitcoinETFHoldings:
    """Franklin Bitcoin ETF (EZBC)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://www.franklintempleton.com/investments/options/exchange-traded-funds/products/39639/SINGLCLASS/franklin-bitcoin-etf/EZBC",
        etf_symbol="EZBC"
    )

async def extract_btcw_holdings() -> BitcoinETFHoldings:
    """WisdomTree Bitcoin Fund (BTCW), manual robust extraction."""
    url = "https://www.wisdomtree.com/investments/etfs/crypto/btcw"
    selector = 'a.fund-modal-trigger[data-href*="all-current-day-holdings"]'  # Button to reveal modal

    # Actions: open the modal!
    actions = [
        {"type": "scroll", "direction": "down"},
        {"type": "scroll", "direction": "down"},
        {"type": "scroll", "direction": "down"},
        {"type": "scroll", "direction": "down"},
        {"type": "scroll", "direction": "down"},
        {"type": "scroll", "direction": "down"},
        {"type": "scroll", "direction": "down"},
        {"type": "wait", "milliseconds": 1200},
        {"type": "click", "selector": selector},
        {"type": "wait", "milliseconds": 3500},
    ]

    # Get the focused screenshot and html _after_ clicking
    focused_content = await screenshot(url, include_dom=True, initial_actions=actions)

    # Use only the focused HTML for markdown (no need to extract by selector again)
    focused_markdown = markdown2.markdown(focused_content.dom)

    prompt = dedent(f"""
        Extract the WisdomTree Bitcoin ETF (BTCW) on-screen data from the below focused holdings-table.
        Parse the **Bitcoin quantity held, its units, total net assets if present, and the 'as of' date**.
        Provide a very short note with any caveats (e.g. if you estimated).
        Respond in the BitcoinETFHoldings model format.

        {focused_markdown}

        website_url: {url}
    """).strip()

    holdings: BitcoinETFHoldings = await call_gemini(
        prompt=prompt,
        pydantic_model=BitcoinETFHoldings,
        temperature=0.15,
        images=[focused_content.screenshot_url],
    )
    return holdings


async def extract_defi_holdings() -> BitcoinETFHoldings:
    """Hashdex Bitcoin ETF (DEFI)"""
    return await screenshot_and_extract_bitcoin_holdings(
        url="https://hashdex-etfs.com/defi",
        etf_symbol="DEFI"
    )
