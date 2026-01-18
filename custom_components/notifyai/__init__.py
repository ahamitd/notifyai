import logging
import re
import os
import json
import base64
import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.const import CONF_API_KEY

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
        CONF_MODEL: entry.options.get(CONF_MODEL, "gemini-flash-latest")
    }

    # Debug: List available models to help user find correct one
    hass.async_create_task(log_available_models(hass, api_key))

    entry.async_on_unload(entry.add_update_listener(update_listener))

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
                hass, api_key, model_name, system_prompt, user_message_text, image_data
            )
            
            # Use custom title if provided, otherwise parse AI response
            if custom_title:
                title = custom_title
                body = response_text.strip()
            else:
                title = ""
                body = ""
                
                lines = response_text.strip().split('\n')
                for line in lines:
                    if line.startswith("Title:"):
                        title = line.replace("Title:", "").strip()
                    elif line.startswith("Body:"):
                        body = line.replace("Body:", "").strip()
                
                if not title and not body:
                     title = "Bildirim"
                     body = response_text

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
                try:
                    # Remove markdown characters and emojis from body for better TTS
                    clean_body = body.replace("*", "").replace("#", "").replace("- ", "").replace("`", "")
                    clean_body = re.sub(r'[\U00010000-\U0010ffff]', '', clean_body)
                    
                    # Modern HA format: tts.speak action
                    # target: entity_id: tts_engine (e.g. tts.google_translate_en_com)
                    # data: media_player_entity_id: speaker (e.g. media_player.homepod)
                    
                    tts_data = {
                        "entity_id": tts_service,
                        "media_player_entity_id": audio_device,
                        "message": clean_body,
                        "cache": True
                    }
                    if language:
                        tts_data["language"] = language
                        
                    await hass.services.async_call(
                        "tts", "speak",
                        tts_data,
                        blocking=False
                    )
                    _LOGGER.info("NotifyAI - TTS (tts.speak) call sent successfully")
                except Exception as e:
                    _LOGGER.error("NotifyAI - Failed to call tts.speak: %s. Falling back to legacy call.", e)
                    # Legacy fallback
                    try:
                        if "." in tts_service:
                            tts_domain, tts_svc = tts_service.split(".", 1)
                            legacy_data = {
                                "entity_id": audio_device, 
                                "message": clean_body,
                                "cache": True
                            }
                            if language:
                                legacy_data["language"] = language
                                
                            await hass.services.async_call(
                                tts_domain, tts_svc,
                                legacy_data,
                                blocking=False
                            )
                            _LOGGER.info("NotifyAI - Legacy TTS call sent successfully")
                    except Exception as e2:
                        _LOGGER.error("NotifyAI - Legacy fallback also failed: %s", e2)

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
    hass.data[DOMAIN].pop(entry.entry_id)
    return True

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
    image_base64: str = None
) -> str:
    """Call Google Gemini API directly via REST."""
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    
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
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Gemini API error ({response.status}): {error_text}")
            
            data = await response.json()
            
            # Extract text from response
            try:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except (KeyError, IndexError) as e:
                raise Exception(f"Unexpected API response format: {data}")

async def log_available_models(hass: HomeAssistant, api_key: str):
    """Query API to list available models and log them."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    models = [m['name'] for m in data.get('models', [])]
                    _LOGGER.warning("✅ NotifyAI - Available Models for your Key: %s", ", ".join(models))
                else:
                    _LOGGER.error("❌ NotifyAI - Could not list models: %s", await response.text())
    except Exception as e:
        _LOGGER.error("❌ NotifyAI - Error listing models: %s", e)
