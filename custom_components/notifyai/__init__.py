import logging
import re
import os
import json
import base64
import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.const import CONF_API_KEY
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.exceptions import HomeAssistantError

from .const import (
    DOMAIN, 
    CONF_API_KEY, 
    CONF_MODEL,
    CONF_NOTIFY_SERVICE_1,
    CONF_NOTIFY_SERVICE_2,
    CONF_NOTIFY_SERVICE_3,
    CONF_NOTIFY_SERVICE_4
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up AI Notification from a config entry."""
    hass.data.setdefault(DOMAIN, {})
    
    api_key = entry.data.get(CONF_API_KEY)
    
    if not api_key:
        _LOGGER.error("No API key found in configuration entry.")
        return False
        
    hass.data[DOMAIN][entry.entry_id] = {
        CONF_API_KEY: api_key,
        CONF_MODEL: entry.options.get(CONF_MODEL, "gemini-flash-latest"),
        "usage_data": {
            "daily_count": 0,
            "last_call_time": None,
            "last_call_status": None,
            "last_reset": None,
            "last_error": None
        }
    }

    # Debug: List available models to help user find correct one
    hass.async_create_task(log_available_models(hass, api_key))

    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    # Set up sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    async def generate_notification(call: ServiceCall) -> ServiceResponse:
        """Handle the service call."""
        from datetime import datetime
        
        event = call.data.get("event")
        custom_title = call.data.get("custom_title")  # New: optional custom title
        context = call.data.get("context", "")  # Optional now
        mode = call.data.get("mode", "smart")  # Default to smart
        persona = call.data.get("persona") 
        image_path = call.data.get("image_path")
        
        # Auto-generate time if not provided
        time = datetime.now().strftime('%H:%M')
        
        # Service call override
        notify_service_arg = call.data.get("notify_service")
        
        # TTS arguments
        audio_device = call.data.get("audio_device")
        tts_service = call.data.get("tts_service", "tts.google_translate_say")
        language = call.data.get("language")

        model_name = hass.data[DOMAIN][entry.entry_id][CONF_MODEL]

        system_prompt = await hass.async_add_executor_job(load_system_prompt, hass)
        if not system_prompt:
             return {"title": "Error", "body": "System prompt missing."}

        if persona:
             system_prompt += f"\n\nIMPORTANT: You must adopt the persona of '{persona}'. Ignore the standard 'Mode' setting. Act exactly like {persona} would."

        # Build user message (context is optional)
        user_message_text = f"""Event: {event}
Time: {time}
Mode: {mode}"""
        
        if context:
            user_message_text += f"\nContext: {context}"

        image_data = None
        if image_path:
            try:
                 image_data = await hass.async_add_executor_job(load_image_base64, image_path)
            except Exception as e:
                _LOGGER.warning("Could not load image at %s: %s", image_path, e)

        try:
            response_text = await call_gemini_api(
                hass, api_key, model_name, system_prompt, user_message_text, image_data, entry.entry_id
            )
            
            # Use custom title if provided, otherwise parse AI response
            if custom_title:
                title = custom_title
                body = response_text.strip()
            else:
                try:
                    # 1. Try strict JSON
                    ai_response = json.loads(response_text)
                    title = ai_response.get("title", "AI Bildirim")
                    body = ai_response.get("body", "")
                except:
                    # 2. Try to find JSON block
                    match = re.search(r'\{.*\}', response_text, re.DOTALL)
                    if match:
                        try:
                            ai_response = json.loads(match.group())
                            title = ai_response.get("title", "AI Bildirim")
                            body = ai_response.get("body", "")
                        except:
                            pass
                    
                    if not title or not body:
                        # 3. Fallback: Parse "Title: ... Body: ..." format
                        title = "Bildirim"
                        body = response_text
                        
                        for line in response_text.split('\n'):
                            clean_line = line.strip()
                            if clean_line.lower().startswith('title:'):
                                title = clean_line.split(':', 1)[1].strip()
                            elif clean_line.lower().startswith('body:'):
                                body = clean_line.split(':', 1)[1].strip()
                            elif clean_line.lower().startswith('başlık:'):
                                title = clean_line.split(':', 1)[1].strip()
                            elif clean_line.lower().startswith('gönderi:'):
                                body = clean_line.split(':', 1)[1].strip()

            # Determine targets
            targets = []
            if notify_service_arg:
                targets.append(notify_service_arg)
            else:
                for key in [CONF_NOTIFY_SERVICE_1, CONF_NOTIFY_SERVICE_2, CONF_NOTIFY_SERVICE_3, CONF_NOTIFY_SERVICE_4]:
                    srv = entry.options.get(key)
                    if srv and srv.strip():
                        targets.append(srv.strip())
            
            # Send to all targets
            for target in targets:
                if "." in target:
                    try:
                        domain, service = target.split(".", 1)
                        await hass.services.async_call(
                            domain, service,
                            {"title": title, "message": body},
                            blocking=False 
                        )
                    except Exception as e:
                         _LOGGER.error("Failed to call notify service %s: %s", target, e)
                else:
                    _LOGGER.warning("Invalid notify_service format: %s", target)
            
            # Send TTS if audio device is selected
            if audio_device and tts_service:
                _LOGGER.info("NotifyAI - Attempting TTS on %s via %s", audio_device, tts_service)
                
                # Combine title and body for a more natural speech experience
                full_message = f"{title}. {body}"
                
                # Remove markdown characters and emojis from body for better TTS
                clean_message = full_message.replace("*", "").replace("#", "").replace("- ", "").replace("`", "")
                clean_message = re.sub(r'[\U00010000-\U0010ffff]', '', clean_message)
                clean_message = clean_message.strip()

                async def perform_tts_call(service_name, service_data, is_legacy=False):
                    """Helper to perform TTS call with language fallback."""
                    try:
                        domain = "tts" if not is_legacy else tts_service.split(".", 1)[0]
                        service = service_name if not is_legacy else tts_service.split(".", 1)[1]
                        
                        _LOGGER.debug("NotifyAI - Calling %s.%s with data: %s", domain, service, service_data)
                        await hass.services.async_call(
                            domain, service, service_data,
                            blocking=True 
                        )
                        return True
                    except Exception as e:
                        error_msg = str(e)
                        _LOGGER.warning("NotifyAI - TTS call failed (%s): %s", service_name, error_msg)
                        
                        # Fallback for language support error
                        if "not supported" in error_msg.lower() and "language" in error_msg.lower() and "language" in service_data:
                            lang = service_data.get("language")
                            
                            # 1. Try normalization (e.g. 'tr' -> 'tr-TR') if it's a 2-char code
                            if lang and len(lang) == 2:
                                normalized_lang = f"{lang}-{lang.upper()}"
                                _LOGGER.info("NotifyAI - Language '%s' failed, trying normalized '%s'", lang, normalized_lang)
                                fallback_data = service_data.copy()
                                fallback_data["language"] = normalized_lang
                                try:
                                    await hass.services.async_call(domain, service, fallback_data, blocking=True)
                                    _LOGGER.info("NotifyAI - TTS successful with normalized language code: %s", normalized_lang)
                                    return True
                                except Exception as e_norm:
                                    _LOGGER.warning("NotifyAI - Normalized language also failed: %s", e_norm)

                            # 2. Last resort: try without language parameter entirely
                            _LOGGER.info("NotifyAI - Language support completely failed for %s, trying without language parameter.", service_name)
                            final_fallback_data = service_data.copy()
                            final_fallback_data.pop("language")
                            
                            try:
                                await hass.services.async_call(
                                    domain, service, final_fallback_data,
                                    blocking=True
                                )
                                _LOGGER.info("NotifyAI - TTS successful without language parameter")
                                return True
                            except Exception as e_final:
                                _LOGGER.error("NotifyAI - All TTS methods failed: %s", e_final)
                        return False

                # 1. Try Modern format: tts.speak
                tts_data = {
                    "entity_id": tts_service,
                    "media_player_entity_id": audio_device,
                    "message": clean_message,
                    "cache": True
                }
                if language:
                    tts_data["language"] = language

                success = await perform_tts_call("speak", tts_data)
                
                # 2. Try Legacy fallback if modern failed and it's not already a legacy service name
                if not success and "." in tts_service and not tts_service.startswith("tts."):
                    legacy_data = {
                        "entity_id": audio_device, 
                        "message": clean_message,
                        "cache": True
                    }
                    if language:
                        legacy_data["language"] = language
                    
                    await perform_tts_call(None, legacy_data, is_legacy=True)

            return {
                "title": title,
                "body": body
            }

        except Exception as e:
            _LOGGER.error("Error generating notification: %s", e)
            return {
                "title": "Error",
                "body": f"AI Generation failed: {str(e)}"
            }

    hass.services.async_register(
        DOMAIN, 
        "generate", 
        generate_notification,
        supports_response=SupportsResponse.OPTIONAL
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    await hass.config_entries.async_reload(entry.entry_id)

def load_system_prompt(hass: HomeAssistant) -> str:
    """Reads the system prompt from the file."""
    prompt_path = hass.config.path("custom_components", DOMAIN, "system_prompt.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        _LOGGER.error("system_prompt.md not found at %s", prompt_path)
        return ""

def load_image_base64(image_path: str) -> str:
    """Loads an image and converts to base64."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found at {image_path}")
    
    with open(image_path, "rb") as f:
        image_bytes = f.read()
    
    return base64.b64encode(image_bytes).decode('utf-8')

async def call_gemini_api(
    hass: HomeAssistant,
    api_key: str, 
    model_name: str, 
    system_prompt: str, 
    user_text: str,
    image_base64: str = None,
    entry_id: str = None
) -> str:
    """Call Google Gemini API directly via REST."""
    from homeassistant.util import dt as dt_util
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    session = async_get_clientsession(hass)
    
    # Build request payload
    contents = []
    parts = [{"text": user_text}]
    
    if image_base64:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": image_base64
            }
        })
    
    contents.append({"parts": parts})
    
    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": contents,
        "generationConfig": {
            "temperature": 0.7
        }
    }
    
    # Track usage if entry_id is provided
    if entry_id and entry_id in hass.data.get(DOMAIN, {}):
        usage_data = hass.data[DOMAIN][entry_id].get("usage_data", {})
        
    async with session.post(url, json=payload) as response:
        if response.status != 200:
            error_text = await response.text()
            
            # Update usage tracking with error
            if entry_id and entry_id in hass.data.get(DOMAIN, {}):
                usage_data = hass.data[DOMAIN][entry_id].get("usage_data", {})
                usage_data["last_call_time"] = dt_util.now().isoformat()
                usage_data["last_call_status"] = f"Hata ({response.status})"
                usage_data["last_error"] = error_text[:200]  # Limit error message length
            
            raise Exception(f"Gemini API error ({response.status}): {error_text}")
        
        data = await response.json()
        
        # Update usage tracking with success
        if entry_id and entry_id in hass.data.get(DOMAIN, {}):
            usage_data = hass.data[DOMAIN][entry_id].get("usage_data", {})
            usage_data["daily_count"] = usage_data.get("daily_count", 0) + 1
            usage_data["last_call_time"] = dt_util.now().isoformat()
            usage_data["last_call_status"] = "Başarılı"
            usage_data["last_error"] = None
        
        # Extract text from response
        try:
            return data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError) as e:
            raise Exception(f"Unexpected API response format: {data}")

async def log_available_models(hass: HomeAssistant, api_key: str):
    """Query API to list available models and log them."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    session = async_get_clientsession(hass)
    try:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                models = [m['name'] for m in data.get('models', [])]
                _LOGGER.warning("✅ NotifyAI - Available Models for your Key: %s", ", ".join(models))
            else:
                _LOGGER.error("❌ NotifyAI - Could not list models: %s", await response.text())
    except Exception as e:
        _LOGGER.error("❌ NotifyAI - Error listing models: %s", e)
