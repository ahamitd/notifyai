import logging
import os
import voluptuous as vol


from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv
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

    entry.async_on_unload(entry.add_update_listener(update_listener))

    async def generate_notification(call: ServiceCall) -> ServiceResponse:
        """Handle the service call."""
        event = call.data.get("event")
        time = call.data.get("time")
        context = call.data.get("context")
        mode = call.data.get("mode")
        persona = call.data.get("persona") 
        image_path = call.data.get("image_path")
        
        # Service call override
        notify_service_arg = call.data.get("notify_service")

        model_name = hass.data[DOMAIN][entry.entry_id][CONF_MODEL]

        system_prompt = await hass.async_add_executor_job(load_system_prompt, hass)
        if not system_prompt:
             return {"title": "Error", "body": "System prompt missing."}

        if persona:
             system_prompt += f"\n\nIMPORTANT: You must adopt the persona of '{persona}'. Ignore the standard 'Mode' setting. Act exactly like {persona} would."

        user_message_parts = []
        user_message_text = f"""
Event: {event}
Time: {time}
Context: {context}
Mode: {mode}
"""
        user_message_parts.append(user_message_text)

        image_data = None
        if image_path:
            try:
                 image_data = await hass.async_add_executor_job(load_image, image_path)
                 if image_data:
                     user_message_parts.append(image_data)
            except Exception as e:
                _LOGGER.warning("Could not load image at %s: %s", image_path, e)

        try:
            response_text = await hass.async_add_executor_job(
                _call_api, api_key, model_name, system_prompt, user_message_parts
            )
            
            title = ""
            body = ""
            
            lines = response_text.strip().split('\n')
            for line in lines:
                if line.startswith("Title:"):
                    title = line.replace("Title:", "").strip()
                elif line.startswith("Body:"):
                    body = line.replace("Body:", "").strip()
            
            if not title and not body:
                 title = "Notification"
                 body = response_text

            # Determine targets
            targets = []
            if notify_service_arg:
                # If provided in call, use ONLY that (override)
                targets.append(notify_service_arg)
            else:
                # Use configured defaults
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
        supports_response=SupportsResponse.ONLY
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id)
    return True

async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener."""
    # We don't need to do anything specific here as we read options dynamically in the service call
    pass

def load_system_prompt(hass: HomeAssistant) -> str:
    """Reads the system prompt from the file."""
    prompt_path = hass.config.path("custom_components", DOMAIN, "system_prompt.md")
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        _LOGGER.error("system_prompt.md not found at %s", prompt_path)
        return ""

def load_image(image_path: str):
    """Loads an image from path using Pillow."""
    from PIL import Image
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found at {image_path}")
    return Image.open(image_path)

def _call_api(api_key: str, model_name: str, system_prompt: str, content_parts: list) -> str:
    """Helper to call the API (blocking I/O)."""
    
    if api_key.startswith("AIza"):
        import google.generativeai as genai
        try:
            genai.configure(api_key=api_key)
            model = genai.GenerativeModel(
                f'models/{model_name}', 
                system_instruction=system_prompt
            )
            response = model.generate_content(content_parts)
            return response.text
        except Exception as e:
            if "404" in str(e) and model_name != "gemini-flash-latest":
                 _LOGGER.warning("Model %s not found (or no vision support), falling back to gemini-flash-latest", model_name)
                 model = genai.GenerativeModel(
                    'models/gemini-flash-latest', 
                    system_instruction=system_prompt
                 )
                 response = model.generate_content(content_parts)
                 return response.text
            raise e

    elif api_key.startswith("sk-"):
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        
        text_content = ""
        for part in content_parts:
            if isinstance(part, str):
                text_content += part
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text_content}
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content
        
    else:
        raise ValueError("Unknown API Key format.")
