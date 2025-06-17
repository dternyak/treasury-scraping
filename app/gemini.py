"""Gemini AI integration for content analysis and processing."""

import base64
import json
from typing import Any, Dict, List, Literal, Optional, TypeVar, Union, cast, overload

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)

DEFAULT_MODEL: str = "gemini-2.5-flash-preview-05-20"
GENAI_RETRIES = 3
GENAI_BACKOFF = 2

# Initialize Gemini client
_client = genai.Client(api_key=settings.GEMINI_API_KEY)

# Retry decorator for Gemini API calls
genai_retry = retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(GENAI_RETRIES),
    wait=wait_fixed(GENAI_BACKOFF),
    reraise=True,
)

P = TypeVar("P", bound=BaseModel)


def _normalize_images(images: List[str]) -> List[str]:
    """Normalize image inputs to a consistent format."""
    if not images:
        return []
    return images if isinstance(images, list) else [images]


async def _bytes_from_source(src: str) -> bytes:
    """Get bytes from image source (URL or data URI)."""
    if src.startswith("http"):
        async with httpx.AsyncClient() as client:
            response = await client.get(src)
            response.raise_for_status()
            return response.content
    if src.startswith("data:"):
        src = src.split(",", 1)[1]
    return base64.b64decode(src)


# Overloads for call_gemini function
@overload
async def call_gemini(
    prompt: Union[str, List[str]],
    *,
    model: str = DEFAULT_MODEL,
    pydantic_model: None = None,
    response_as_json: Literal[False] = False,
    temperature: float = 0.7,
    images: Union[str, List[str], None] = None,
) -> str: ...

@overload
async def call_gemini(
    prompt: Union[str, List[str]],
    *,
    model: str = DEFAULT_MODEL,
    pydantic_model: None = None,
    response_as_json: Literal[True],
    temperature: float = 0.7,
    images: Union[str, List[str], None] = None,
) -> Dict[str, Any]: ...

@overload
async def call_gemini(
    prompt: Union[str, List[str]],
    *,
    model: str = DEFAULT_MODEL,
    pydantic_model: type[P],
    response_as_json: Literal[False] = False,
    temperature: float = 0.7,
    images: Union[str, List[str], None] = None,
) -> P: ...


@genai_retry
async def call_gemini(
    prompt: Union[str, List[str]],
    *,
    model: str = DEFAULT_MODEL,
    pydantic_model: Optional[type[P]] = None,
    response_as_json: bool = False,
    temperature: float = 0.7,
    images: Union[str, List[str], None] = None,
) -> Union[str, Dict[str, Any], P]:
    """
    Call the Gemini AI API with text and optional images.
    
    Args:
        prompt: Text prompt(s) to send to Gemini
        model: Gemini model to use
        pydantic_model: Optional Pydantic model for structured output
        response_as_json: Whether to return JSON response
        temperature: Sampling temperature (0.0 to 1.0)
        images: Optional image URLs or data URIs
        
    Returns:
        String response, JSON dict, or Pydantic model instance
    """
    logger.info(f"Calling Gemini API with model: {model}")
    
    # Build a list of Part objects
    parts: List[types.Part] = []
    
    # Add text parts
    if isinstance(prompt, list):
        parts.extend(types.Part.from_text(text=p) for p in prompt)
    else:
        parts.append(types.Part.from_text(text=prompt))
    
    # Add image parts
    for img in _normalize_images(images or []):
        try:
            raw = await _bytes_from_source(img)
            parts.append(types.Part.from_bytes(data=raw, mime_type="image/jpeg"))
        except Exception as e:
            logger.warning(f"Failed to load image {img}: {e}")
            continue

    # Build config
    cfg_kwargs: Dict[str, Any] = {"temperature": temperature}
    
    if pydantic_model is not None:
        cfg_kwargs["response_mime_type"] = "application/json"
        cfg_kwargs["response_schema"] = cast(Any, pydantic_model)
    elif response_as_json:
        cfg_kwargs["response_mime_type"] = "application/json"
    
    config = types.GenerateContentConfig(**cfg_kwargs)
    content = types.Content(parts=parts)

    try:
        response = await _client.aio.models.generate_content(
            model=model,
            contents=content,
            config=config,
        )
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        raise

    # Handle Pydantic model response
    if pydantic_model is not None:
        parsed_obj = getattr(response, "parsed", None)
        if parsed_obj is not None:
            return cast(P, parsed_obj)
        
        txt = response.text or ""
        try:
            data = json.loads(txt)
        except Exception as e:
            logger.error(f"Bad JSON from Gemini: {e}\n{txt}")
            raise RuntimeError("Invalid JSON response from Gemini") from e
        
        try:
            if hasattr(pydantic_model, "model_validate"):
                return pydantic_model.model_validate(data)
            return pydantic_model.parse_obj(data)
        except ValidationError as ve:
            logger.error(f"Pydantic validation error: {ve}")
            raise RuntimeError("Pydantic validation error") from ve

    # Handle regular response
    if response is None:
        raise RuntimeError("No response returned from Gemini")
    
    txt = response.text
    if txt is None:
        raise RuntimeError("No text returned from Gemini")
    
    if response_as_json:
        try:
            return json.loads(txt)
        except Exception as e:
            logger.error(f"Bad JSON from Gemini: {e}\n{txt}")
            raise RuntimeError("Invalid JSON response from Gemini") from e
    
    return txt



