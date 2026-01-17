import logging
import voluptuous as vol
import aiohttp
from homeassistant import config_entries
from homeassistant.core import callback
from .const import (
    DOMAIN, 
    CONF_API_KEY, 
    CONF_MODEL,
    CONF_NOTIFY_SERVICE_1,
    CONF_NOTIFY_SERVICE_2,
    CONF_NOTIFY_SERVICE_3,
    CONF_NOTIFY_SERVICE_4,
    MODEL_OPTIONS,
    DEFAULT_MODEL
)

_LOGGER = logging.getLogger(__name__)

class AiNotificationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AI Notification."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        if user_input is not None:
            # Validate input (simple check if key is not empty)
            if not user_input[CONF_API_KEY]:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title="AI Notification", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
            }),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AiNotificationOptionsFlowHandler()

async def fetch_models(api_key):
    """Fetch available models from Google API."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    # Filter and format models
                    models = {}
                    for m in data.get('models', []):
                        name = m['name'].replace('models/', '')
                        if 'gemini' in name and 'vision' not in name: # Basic filtering
                             friendly_name = m.get('displayName', name)
                             models[name] = f"{friendly_name} ({name})"
                    return models
    except Exception as e:
        _LOGGER.error("Error fetching models: %s", e)
    return None

class AiNotificationOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_model = self.config_entry.options.get(CONF_MODEL, DEFAULT_MODEL)
        
        # 1. Try to fetch models dynamically
        api_key = self.config_entry.data.get(CONF_API_KEY)
        dynamic_models = await fetch_models(api_key)
        
        # 2. Use dynamic list if available, otherwise fallback to hardcoded
        if dynamic_models:
            model_options = dynamic_models
            # Ensure current selection is valid or default to first available
            if current_model not in model_options:
                current_model = list(model_options.keys())[0]
        else:
            model_options = MODEL_OPTIONS
            if current_model not in model_options:
                 current_model = DEFAULT_MODEL

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_MODEL, default=current_model): vol.In(model_options),
                vol.Optional(CONF_NOTIFY_SERVICE_1, default=self.config_entry.options.get(CONF_NOTIFY_SERVICE_1, "")): str,
                vol.Optional(CONF_NOTIFY_SERVICE_2, default=self.config_entry.options.get(CONF_NOTIFY_SERVICE_2, "")): str,
                vol.Optional(CONF_NOTIFY_SERVICE_3, default=self.config_entry.options.get(CONF_NOTIFY_SERVICE_3, "")): str,
                vol.Optional(CONF_NOTIFY_SERVICE_4, default=self.config_entry.options.get(CONF_NOTIFY_SERVICE_4, "")): str,
            }),
        )
