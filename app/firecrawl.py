"""Firecrawl integration for web scraping and screenshot functionality."""

from typing import Any, Dict, List, Literal, Optional, Union, overload

import httpx
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

FIRECRAWL_BASE_URL = "https://api.firecrawl.dev/"
FIRECRAWL_PAGE_TIMEOUT_MSEC = 60_000
SCRAPE_TIMEOUT = httpx.Timeout(30)
SCRAPE_ATTEMPTS = 3


# In your models/schemas file

class ScreenshotResult(BaseModel):
    """Result of a standard screenshot operation."""
    url: str
    title: str
    screenshot_url: str

class ScreenshotAndDOMResult(ScreenshotResult):
    """Result of a screenshot operation that also includes the page's DOM."""
    dom: str

class FocusedResult(BaseModel):
    """Result of a focused operation: a viewport screenshot and specific element HTML."""
    screenshot_url: str
    html_content: str

class SearchResult(BaseModel):
    url: str
    title: str
    description: str


class SearchResults(BaseModel):
    results: list[SearchResult]


class ScrapeError(BaseModel):
    class Config:
        arbitrary_types_allowed = True

    url: str
    error: Exception


class FirecrawlResponseFormatError(Exception):
    """Raised when firecrawl response doesn't conform to the expectation."""
    pass


class ScrapeResult(BaseModel):
    """Result of a scrape operation."""
    url: str
    title: Optional[str]
    content: str


def default_scrape_payload() -> Dict[str, Any]:
    """Get default payload for scrape requests."""
    return {
        "timeout": FIRECRAWL_PAGE_TIMEOUT_MSEC,
        "onlyMainContent": False,
        "skipTlsVerification": True
    }


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, FirecrawlResponseFormatError)),
    stop=stop_after_attempt(SCRAPE_ATTEMPTS),
    wait=wait_fixed(2),
    reraise=True,
)
async def call_firecrawl(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Make a call to the Firecrawl API."""
    api_url = FIRECRAWL_BASE_URL + path
    headers = {
        "Authorization": f"Bearer {settings.FIRECRAWL_API_KEY}",
        "Content-Type": "application/json",
    }
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                api_url,
                headers=headers,
                json=payload,
                timeout=SCRAPE_TIMEOUT,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.error(f"HTTP error occurred while calling Firecrawl API: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error occurred while calling Firecrawl API: {e}")
            raise


@retry(
    retry=retry_if_exception_type(FirecrawlResponseFormatError),
    reraise=True,
    stop=stop_after_attempt(3),
)
async def scrape(
    url: str,
    response_format: str = "rawHtml",
    *,
    only_main_content: bool = False,
) -> ScrapeResult:
    """Scrape a URL and return the content."""
    logger.info(f"Scraping URL: {url}")
    
    data = await call_firecrawl(
        "v1/scrape",
        {
            **default_scrape_payload(),
            "url": url,
            "formats": [response_format],
            "onlyMainContent": only_main_content,
        },
    )
    
    try:
        response_url = data["data"]["metadata"]["sourceURL"]
        title = data["data"]["metadata"].get("title")
        content = data["data"][response_format]
    except KeyError as e:
        logger.error(f"Malformed response from Firecrawl API: missing key {e}")
        raise FirecrawlResponseFormatError(data) from e

    if len(content) == 0:
        raise FirecrawlResponseFormatError("Empty content returned")

    # Handle title being a list (Firecrawl bug)
    if isinstance(title, list):
        title = title[0] if title else None

    return ScrapeResult(url=response_url, title=title, content=content)


# Overloads for screenshot function
@overload
async def screenshot(
    url: str,
    *,
    selector: str,
    initial_actions: Optional[List[Dict[str, Any]]] = None
) -> FocusedResult: ...

@overload
async def screenshot(
    url: str,
    *,
    full_page: bool = True,
    include_dom: Literal[True],
    selector: None = None,
    initial_actions: Optional[List[Dict[str, Any]]] = None
) -> ScreenshotAndDOMResult: ...

@overload
async def screenshot(
    url: str,
    *,
    full_page: bool = True,
    include_dom: Literal[False],
    selector: None = None,
    initial_actions: Optional[List[Dict[str, Any]]] = None
) -> ScreenshotResult: ...

@overload
async def screenshot(
    url: str,
    *,
    full_page: bool = True,
    include_dom: bool = False,
    selector: None = None,
    initial_actions: Optional[List[Dict[str, Any]]] = None
) -> Union[ScreenshotResult, ScreenshotAndDOMResult]: ...


@retry(
    retry=retry_if_exception_type(FirecrawlResponseFormatError),
    reraise=True,
    stop=stop_after_attempt(3),
)
async def screenshot(
    url: str,
    *,
    full_page: bool = True,
    include_dom: bool = False,
    selector: Optional[str] = None,
    initial_actions: Optional[List[Dict[str, Any]]] = None,
) -> Union[ScreenshotResult, ScreenshotAndDOMResult, FocusedResult]:
    """
    Take a screenshot of a webpage with multiple modes.
    
    - Default Mode: Takes a simple screenshot. Returns ScreenshotResult.
    - DOM Mode (include_dom=True): Takes a screenshot and gets the full DOM.
      Returns ScreenshotAndDOMResult.
    - Focus Mode (selector="..."): Scrolls to an element, takes a viewport
      screenshot, and extracts the element's HTML. Returns FocusedResult.
    """
    # FOCUS MODE: If a selector is provided
    if selector:
        logger.info(f"Executing focus mode: scrolling to '{selector}' on {url}")
        actions = initial_actions or []
        actions += [
            {"type": "wait", "milliseconds": 3000},
            {"type": "scroll", "selector": selector},
            {"type": "screenshot"},
            {"type": "scrape", "selector": selector},
        ]
        
        payload = {
            **default_scrape_payload(),
            "url": url,
            "actions": actions,
            "formats": [],
        }
        
        data = await call_firecrawl("v1/scrape", payload)
        
        try:
            action_data = data["data"]["actions"]
            focused_screenshot_url = action_data["screenshots"][0]
            focused_html = action_data["scrapes"][0]["html"]
            
            if not focused_screenshot_url or not focused_html:
                raise KeyError("Missing screenshot or HTML in action response")
                
            return FocusedResult(
                screenshot_url=focused_screenshot_url,
                html_content=focused_html
            )
        except (KeyError, IndexError) as e:
            raise FirecrawlResponseFormatError(f"Could not parse focus mode response: {e}") from e

    # STANDARD & DOM MODES
    else:
        logger.info(f"Executing standard screenshot (include_dom={include_dom}) for {url}")
        formats = ["screenshot@fullPage" if full_page else "screenshot"]
        if include_dom:
            formats.append("rawHtml")

        payload = {
            **default_scrape_payload(),
            "url": url,
            "formats": formats
        }
        
        if initial_actions:
            payload["actions"] = initial_actions

        data = await call_firecrawl("v1/scrape", payload)

        try:
            source_url = data["data"]["metadata"]["sourceURL"]
            title = data["data"]["metadata"].get("title", "")
            screenshot_url = data["data"]["screenshot"]
            
            if not isinstance(screenshot_url, str) or not screenshot_url.startswith("https://"):
                raise FirecrawlResponseFormatError(f"Invalid screenshot URL: {screenshot_url}")

            if include_dom:
                dom = data["data"].get("rawHtml")
                if not isinstance(dom, str) or not dom:
                    raise FirecrawlResponseFormatError("Requested DOM but got invalid content.")
                return ScreenshotAndDOMResult(
                    url=source_url,
                    title=title,
                    screenshot_url=screenshot_url,
                    dom=dom
                )
            else:
                return ScreenshotResult(
                    url=source_url,
                    title=title,
                    screenshot_url=screenshot_url
                )
        except KeyError as e:
            raise FirecrawlResponseFormatError(f"Missing expected key in standard response: {e}") from e

