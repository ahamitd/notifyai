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
    DEFAULT_MODEL,
    CONF_AI_PROVIDER,
    CONF_GROQ_API_KEY,
    AI_PROVIDERS,
    GROQ_MODELS,
    DEFAULT_GROQ_MODEL,
    GROQ_MODEL_LIMITS
)

_LOGGER = logging.getLogger(__name__)

class AiNotificationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AI Notification."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step - provider selection."""
        errors = {}
        if user_input is not None:
            # Store provider selection and move to API key step
            self.provider = user_input.get(CONF_AI_PROVIDER, "gemini")
            return await self.async_step_api_key()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_AI_PROVIDER, default="gemini"): vol.In(AI_PROVIDERS),
            }),
            errors=errors
        )
    
    async def async_step_api_key(self, user_input=None):
        """Handle API key entry based on selected provider."""
        errors = {}
        
        # Ensure provider is set
        if not hasattr(self, 'provider'):
            return await self.async_step_user()
        
        if user_input is not None:
            if self.provider == "gemini":
                api_key = user_input.get(CONF_API_KEY)
                if not api_key:
                    errors["base"] = "invalid_api_key"
                else:
                    return self.async_create_entry(
                        title="NotifyAI (Gemini)", 
                        data={
                            CONF_AI_PROVIDER: "gemini",
                            CONF_API_KEY: api_key
                        }
                    )
            elif self.provider == "groq":
                groq_key = user_input.get(CONF_GROQ_API_KEY)
                if not groq_key:
                    errors["base"] = "invalid_api_key"
                else:
                    return self.async_create_entry(
                        title="NotifyAI (Groq)",
                        data={
                            CONF_AI_PROVIDER: "groq",
                            CONF_GROQ_API_KEY: groq_key
                        }
                    )
        
        # Show appropriate form based on provider
        if self.provider == "gemini":
            data_schema = vol.Schema({
                vol.Required(CONF_API_KEY): str,
            })
        else:  # groq
            data_schema = vol.Schema({
                vol.Required(CONF_GROQ_API_KEY): str,
            })
        
        return self.async_show_form(
            step_id="api_key",
            data_schema=data_schema,
            errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return AiNotificationOptionsFlowHandler(config_entry)

async def fetch_models(api_key):
    """Fetch available models from Google API with rate limits."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    models = {}
                    model_limits = {}  # Store RPM and RPD limits
                    
                    for m in data.get('models', []):
                        name = m['name'].replace('models/', '')
                        
                        # Filter: only gemini models, exclude vision/embedding
                        if 'gemini' not in name or 'vision' in name or 'embedding' in name:
                            continue
                        
                        # Get rate limits
                        rate_limits = m.get('rateLimits', {})
                        rpm = rate_limits.get('requestsPerMinute', 0)
                        rpd = rate_limits.get('requestsPerDay', 0)
                        
                        # Store both RPM and RPD
                        model_limits[name] = {'rpm': rpm, 'rpd': rpd}
                        
                        # Format display name with RPM and RPD
                        friendly_name = m.get('displayName', name)
                        if rpm > 0 and rpd > 0:
                            models[name] = f"{friendly_name} ({rpm} RPM, {rpd}/gün)"
                        elif rpm > 0:
                            models[name] = f"{friendly_name} ({rpm} RPM)"
                        else:
                            models[name] = f"{friendly_name}"
                    
                    # Return models dict, best model (highest RPD), and limits
                    best_model = max(model_limits, key=lambda k: model_limits[k]['rpd']) if model_limits else None
                    return models, best_model, model_limits
                    
    except Exception as e:
        _LOGGER.error("Error fetching models: %s", e)
    return None, None, None

async def validate_model(api_key, model_name):
    """Try a tiny generateContent call to check quota/availability."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": "hi"}]}],
        "generationConfig": {"maxOutputTokens": 1}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    return True, None
                else:
                    error_data = await response.json()
                    error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                    return False, f"API Error ({response.status}): {error_msg}"
    except Exception as e:
        return False, str(e)

async def validate_groq_model(api_key, model_name):
    """Validate Groq model with a minimal chat completion request."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers) as response:
                if response.status == 200:
                    return True, None
                else:
                    error_data = await response.json()
                    error_msg = error_data.get('error', {}).get('message', 'Unknown error')
                    return False, f"API Error ({response.status}): {error_msg}"
    except Exception as e:
        return False, str(e)

class AiNotificationOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self._config_entry = config_entry

    def _mask_api_key(self, api_key: str) -> str:
        """Mask API key for display (show first 3 and last 3 characters)."""
        if not api_key or len(api_key) < 8:
            return "***"
        return f"{api_key[:3]}...{api_key[-3:]}"

    async def async_step_init(self, user_input=None):
        """Manage the main options - Model and Notification Services."""
        errors = {}
        provider = self._config_entry.data.get(CONF_AI_PROVIDER, "gemini")
        
        # Get appropriate API key
        if provider == "gemini":
            api_key = self._config_entry.data.get(CONF_API_KEY)
        else:  # groq
            api_key = self._config_entry.data.get(CONF_GROQ_API_KEY)
        
        # Get masked key and provider display name for UI
        masked_key = self._mask_api_key(api_key)
        provider_display = "Google Gemini" if provider == "gemini" else "Groq"
        
        # Handle navigation to advanced settings
        if user_input is not None and user_input.get("advanced_settings"):
            return await self.async_step_advanced()
        
        # We need to maintain the list of available models across steps if validation fails
        if "model_options" not in self.hass.data.get(DOMAIN, {}):
            if provider == "gemini":
                dynamic_models, _, _ = await fetch_models(api_key)
                model_options = dynamic_models if dynamic_models else MODEL_OPTIONS
            else:  # groq
                model_options = GROQ_MODELS
        else:
            model_options = GROQ_MODELS if provider == "groq" else MODEL_OPTIONS

        if user_input is not None and not user_input.get("advanced_settings"):
            # Check if model has changed
            current_model = self._config_entry.options.get(CONF_MODEL)
            new_model = user_input.get(CONF_MODEL)
            model_changed = current_model != new_model
            
            # Check if notification services have changed
            notify_changed = False
            for key in [CONF_NOTIFY_SERVICE_1, CONF_NOTIFY_SERVICE_2, CONF_NOTIFY_SERVICE_3, CONF_NOTIFY_SERVICE_4]:
                if self._config_entry.options.get(key, "") != user_input.get(key, ""):
                    notify_changed = True
                    break
            
            # Only validate if model has changed
            if model_changed:
                # Call appropriate validation based on provider
                if provider == "groq":
                    success, error_msg = await validate_groq_model(api_key, new_model)
                else:  # gemini
                    success, error_msg = await validate_model(api_key, new_model)
                
                if not success:
                    _LOGGER.error("Model validation failed: %s", error_msg)
                    if "quota" in error_msg.lower() or "429" in error_msg:
                        errors[CONF_MODEL] = "quota_exceeded"
                    else:
                        errors[CONF_MODEL] = "invalid_model"
            
            # Save changes if no errors (either validation passed or no validation needed)
            if not errors:
                return self.async_create_entry(title="", data=user_input)

        current_model = self._config_entry.options.get(CONF_MODEL)
        
        # Fetch models based on provider
        if provider == "gemini":
            # 1. Fetch Gemini models dynamically
            dynamic_models, best_model, model_limits = await fetch_models(api_key)
            
            # Store model limits in hass.data for sensors
            if model_limits:
                if DOMAIN not in self.hass.data:
                    self.hass.data[DOMAIN] = {}
                self.hass.data[DOMAIN]["model_limits"] = model_limits
            
            # 2. Use dynamic list ONLY if available
            if dynamic_models:
                model_options = dynamic_models
                
                # If no model selected yet, use the best model from API
                if not current_model and best_model:
                    current_model = best_model
                elif not current_model:
                    current_model = DEFAULT_MODEL
                
                # Ensure current model is in available options
                if current_model not in model_options:
                    # Try best model first
                    if best_model and best_model in model_options:
                        current_model = best_model
                    else:
                        # Fallback to first available
                        current_model = list(model_options.keys())[0] if model_options else DEFAULT_MODEL
            else:
                model_options = MODEL_OPTIONS
                if not current_model:
                    current_model = DEFAULT_MODEL
                elif current_model not in model_options:
                    current_model = DEFAULT_MODEL
        else:  # groq
            # Use static Groq models
            model_options = GROQ_MODELS
            model_limits = GROQ_MODEL_LIMITS
            
            # Store model limits in hass.data for sensors
            if DOMAIN not in self.hass.data:
                self.hass.data[DOMAIN] = {}
            self.hass.data[DOMAIN]["model_limits"] = model_limits
            
            if not current_model:
                current_model = DEFAULT_GROQ_MODEL
            elif current_model not in model_options:
                current_model = DEFAULT_GROQ_MODEL

        # Get provider display name
        provider_display = "Google Gemini" if provider == "gemini" else "Groq"
        masked_key = self._mask_api_key(api_key)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_MODEL, default=current_model): vol.In(model_options),
                vol.Optional(CONF_NOTIFY_SERVICE_1, default=self._config_entry.options.get(CONF_NOTIFY_SERVICE_1, "")): str,
                vol.Optional(CONF_NOTIFY_SERVICE_2, default=self._config_entry.options.get(CONF_NOTIFY_SERVICE_2, "")): str,
                vol.Optional(CONF_NOTIFY_SERVICE_3, default=self._config_entry.options.get(CONF_NOTIFY_SERVICE_3, "")): str,
                vol.Optional(CONF_NOTIFY_SERVICE_4, default=self._config_entry.options.get(CONF_NOTIFY_SERVICE_4, "")): str,
                vol.Optional("advanced_settings", default=False): bool,
            }),
            errors=errors
        )

    async def async_step_advanced(self, user_input=None):
        """Handle advanced settings - API key and provider management."""
        provider = self._config_entry.data.get(CONF_AI_PROVIDER, "gemini")
        
        # Get appropriate API key
        if provider == "gemini":
            api_key = self._config_entry.data.get(CONF_API_KEY)
        else:  # groq
            api_key = self._config_entry.data.get(CONF_GROQ_API_KEY)
        
        masked_key = self._mask_api_key(api_key)
        provider_display = "Google Gemini" if provider == "gemini" else "Groq"
        
        if user_input is not None:
            action = user_input.get("action")
            
            if action == "change_api_key":
                return await self.async_step_change_api_key()
            elif action == "change_provider":
                return await self.async_step_change_provider()
            elif action == "back":
                return await self.async_step_init()
        
        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema({
                vol.Required("action", default="back"): vol.In({
                    "change_api_key": "🔑 API Anahtarını Değiştir",
                    "change_provider": "🔄 Sağlayıcıyı Değiştir",
                    "back": "⬅️ Ana Ayarlara Dön"
                }),
            })
        )

    async def async_step_change_api_key(self, user_input=None):
        """Handle API key change."""
        errors = {}
        provider = self._config_entry.data.get(CONF_AI_PROVIDER, "gemini")
        
        if user_input is not None:
            new_api_key = user_input.get("new_api_key")
            
            if not new_api_key or len(new_api_key) < 10:
                errors["new_api_key"] = "invalid_api_key"
            else:
                # Validate the new API key
                if provider == "gemini":
                    # Try to fetch models with new key
                    models, _, _ = await fetch_models(new_api_key)
                    if models:
                        # Update config entry data
                        new_data = dict(self._config_entry.data)
                        new_data[CONF_API_KEY] = new_api_key
                        self.hass.config_entries.async_update_entry(
                            self._config_entry, data=new_data
                        )
                        # Reload the integration
                        await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                        return self.async_create_entry(title="", data={})
                    else:
                        errors["new_api_key"] = "invalid_api_key"
                else:  # groq
                    # Validate with a test model
                    success, error_msg = await validate_groq_model(new_api_key, DEFAULT_GROQ_MODEL)
                    if success:
                        # Update config entry data
                        new_data = dict(self._config_entry.data)
                        new_data[CONF_GROQ_API_KEY] = new_api_key
                        self.hass.config_entries.async_update_entry(
                            self._config_entry, data=new_data
                        )
                        # Reload the integration
                        await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                        return self.async_create_entry(title="", data={})
                    else:
                        errors["new_api_key"] = "invalid_api_key"
        
        provider_display = "Google Gemini" if provider == "gemini" else "Groq"
        api_url = "https://aistudio.google.com/apikey" if provider == "gemini" else "https://console.groq.com/keys"
        
        if provider == "gemini":
            instructions = (
                "**📍 Yeni Gemini API Anahtarı Nasıl Alınır?**\\n\\n"
                "1. https://aistudio.google.com/apikey adresine gidin\\n"
                "2. Google hesabınızla giriş yapın\\n"
                "3. 'Create API Key' butonuna tıklayın\\n"
                "4. Oluşturulan anahtarı kopyalayın ve aşağıya yapıştırın\\n\\n"
                "**⚠️ Önemli:** Yeni anahtar doğrulandıktan sonra entegrasyon otomatik olarak yeniden yüklenecektir."
            )
        else:
            instructions = (
                "**📍 Yeni Groq API Anahtarı Nasıl Alınır?**\\n\\n"
                "1. https://console.groq.com/keys adresine gidin\\n"
                "2. Groq hesabınızla giriş yapın\\n"
                "3. 'Create API Key' butonuna tıklayın\\n"
                "4. Anahtar adı verin ve 'Submit' yapın\\n"
                "5. Oluşturulan anahtarı kopyalayın ve aşağıya yapıştırın\\n\\n"
                "**⚠️ Önemli:** Yeni anahtar doğrulandıktan sonra entegrasyon otomatik olarak yeniden yüklenecektir."
            )
        
        return self.async_show_form(
            step_id="change_api_key",
            data_schema=vol.Schema({
                vol.Required("new_api_key"): str,
            }),
            errors=errors
        )

    async def async_step_change_provider(self, user_input=None):
        """Handle provider change."""
        errors = {}
        current_provider = self._config_entry.data.get(CONF_AI_PROVIDER, "gemini")
        
        if user_input is not None:
            new_provider = user_input.get(CONF_AI_PROVIDER)
            
            # Get the appropriate API key field
            if new_provider == "gemini":
                new_api_key = user_input.get(CONF_API_KEY)
                if not new_api_key:
                    errors[CONF_API_KEY] = "invalid_api_key"
                else:
                    # Validate Gemini key
                    models, _, _ = await fetch_models(new_api_key)
                    if models:
                        # Update config entry
                        new_data = {
                            CONF_AI_PROVIDER: "gemini",
                            CONF_API_KEY: new_api_key
                        }
                        
                        self.hass.config_entries.async_update_entry(
                            self._config_entry, data=new_data
                        )
                        
                        # Reset model to default and reload
                        await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                        return self.async_create_entry(title="", data={CONF_MODEL: DEFAULT_MODEL})
                    else:
                        errors[CONF_API_KEY] = "invalid_api_key"
            else:  # groq
                new_api_key = user_input.get(CONF_GROQ_API_KEY)
                if not new_api_key:
                    errors[CONF_GROQ_API_KEY] = "invalid_api_key"
                else:
                    # Validate Groq key
                    success, _ = await validate_groq_model(new_api_key, DEFAULT_GROQ_MODEL)
                    if success:
                        # Update config entry
                        new_data = {
                            CONF_AI_PROVIDER: "groq",
                            CONF_GROQ_API_KEY: new_api_key
                        }
                        
                        self.hass.config_entries.async_update_entry(
                            self._config_entry, data=new_data
                        )
                        
                        # Reset model to default and reload
                        await self.hass.config_entries.async_reload(self._config_entry.entry_id)
                        return self.async_create_entry(title="", data={CONF_MODEL: DEFAULT_GROQ_MODEL})
                    else:
                        errors[CONF_GROQ_API_KEY] = "invalid_api_key"
        
        # Determine which provider to suggest (opposite of current)
        suggested_provider = "groq" if current_provider == "gemini" else "gemini"
        
        return self.async_show_form(
            step_id="change_provider",
            data_schema=vol.Schema({
                vol.Required(CONF_AI_PROVIDER, default=suggested_provider): vol.In(AI_PROVIDERS),
                vol.Optional(CONF_API_KEY): str,
                vol.Optional(CONF_GROQ_API_KEY): str,
            }),
            errors=errors,
            description_placeholders={
                "current_provider": f"Mevcut: {current_provider}",
                "info": "⚠️ Yeni sağlayıcıyı seçin ve ilgili API anahtarını girin.\\n\\nModel otomatik olarak varsayılana sıfırlanacak.\\n\\n📍 Gemini: https://aistudio.google.com/apikey\\n📍 Groq: https://console.groq.com/keys"
            }
        )
