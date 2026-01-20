"""Sensor platform for NotifyAI integration."""
import logging
from datetime import datetime, timedelta
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, CONF_MODEL, MODEL_LIMITS_FALLBACK

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up NotifyAI sensor based on a config entry."""
    async_add_entities([
        NotifyAIUsageSensor(hass, entry),
        NotifyAIRemainingRequestsSensor(hass, entry),
        NotifyAIDailyLimitSensor(hass, entry),
    ], True)

class NotifyAIUsageSensor(SensorEntity):
    """Sensor to track NotifyAI API usage."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._hass = hass
        self._entry = entry
        self._attr_name = "NotifyAI API Kullanımı"
        self._attr_unique_id = f"{entry.entry_id}_api_usage"
        self._attr_icon = "mdi:api"
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_native_unit_of_measurement = "çağrı"

    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "NotifyAI",
            "manufacturer": "NotifyAI",
            "model": "API Integration",
        }

    @property
    def native_value(self):
        """Return the state of the sensor."""
        usage_data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("usage_data", {})
        
        # Check if we need to reset daily counter
        last_reset = usage_data.get("last_reset")
        now = dt_util.now()
        
        if last_reset:
            last_reset_dt = datetime.fromisoformat(last_reset)
            # Reset if it's a new day
            if last_reset_dt.date() < now.date():
                usage_data["daily_count"] = 0
                usage_data["last_reset"] = now.isoformat()
        else:
            # First time setup
            usage_data["daily_count"] = 0
            usage_data["last_reset"] = now.isoformat()
        
        return usage_data.get("daily_count", 0)

    @property
    def extra_state_attributes(self):
        """Return additional state attributes."""
        usage_data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("usage_data", {})
        current_model = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get(CONF_MODEL, "Bilinmiyor")
        
        attributes = {
            "current_model": current_model,
            "last_call_time": usage_data.get("last_call_time", "Henüz çağrı yapılmadı"),
            "last_call_status": usage_data.get("last_call_status", "Bilinmiyor"),
            "daily_count": usage_data.get("daily_count", 0),
            "last_reset": usage_data.get("last_reset", "Henüz sıfırlanmadı"),
        }
        
        # Add error message if last call failed
        if usage_data.get("last_error"):
            attributes["last_error"] = usage_data.get("last_error")
        
        return attributes

    async def async_update(self):
        """Update the sensor."""
        # The state is computed from hass.data, so we just need to trigger a state update
        pass


class NotifyAIRemainingRequestsSensor(SensorEntity):
    """Sensor to track remaining API requests."""
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._hass = hass
        self._entry = entry
        self._attr_name = "NotifyAI Kalan Sorgu"
        self._attr_unique_id = f"{entry.entry_id}_remaining_requests"
        self._attr_icon = "mdi:counter"
        self._attr_native_unit_of_measurement = "sorgu"
    
    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "NotifyAI",
            "manufacturer": "NotifyAI",
            "model": "API Integration",
        }
    
    @property
    def native_value(self):
        """Return remaining requests."""
        usage_data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("usage_data", {})
        daily_count = usage_data.get("daily_count", 0)
        
        # Get daily limit from model
        model_name = self._entry.options.get(CONF_MODEL, "gemini-2.5-flash")
        daily_limit = self._get_model_daily_limit(model_name)
        
        remaining = max(0, daily_limit - daily_count)
        return remaining
    
    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        usage_data = self._hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {}).get("usage_data", {})
        model_name = self._entry.options.get(CONF_MODEL, "gemini-2.5-flash")
        daily_limit = self._get_model_daily_limit(model_name)
        daily_count = usage_data.get("daily_count", 0)
        
        return {
            "model": model_name,
            "daily_limit": daily_limit,
            "used": daily_count,
        }
    
    def _get_model_daily_limit(self, model_name):
        """Get daily limit for the model."""
        # Try to get from API-fetched limits
        model_limits = self._hass.data.get(DOMAIN, {}).get("model_limits", {})
        if model_name in model_limits:
            return model_limits[model_name].get('rpd', 1500)
        
        # Fallback to hardcoded limits
        return MODEL_LIMITS_FALLBACK.get(model_name, {}).get('rpd', 1500)
    
    async def async_update(self):
        """Update the sensor."""
        pass


class NotifyAIDailyLimitSensor(SensorEntity):
    """Sensor to show daily limit for selected model."""
    
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        self._hass = hass
        self._entry = entry
        self._attr_name = "NotifyAI Günlük Limit"
        self._attr_unique_id = f"{entry.entry_id}_daily_limit"
        self._attr_icon = "mdi:gauge"
        self._attr_native_unit_of_measurement = "sorgu"
    
    @property
    def device_info(self):
        """Return device information about this entity."""
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "NotifyAI",
            "manufacturer": "NotifyAI",
            "model": "API Integration",
        }
    
    @property
    def native_value(self):
        """Return daily limit for current model."""
        model_name = self._entry.options.get(CONF_MODEL, "gemini-2.5-flash")
        return self._get_model_daily_limit(model_name)
    
    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        model_name = self._entry.options.get(CONF_MODEL, "gemini-2.5-flash")
        model_limits = self._hass.data.get(DOMAIN, {}).get("model_limits", {})
        
        # Get limits from API or fallback
        if model_name in model_limits:
            rpm = model_limits[model_name].get('rpm', 15)
            rpd = model_limits[model_name].get('rpd', 1500)
        else:
            limits = MODEL_LIMITS_FALLBACK.get(model_name, {"rpm": 15, "rpd": 1500})
            rpm = limits['rpm']
            rpd = limits['rpd']
        
        return {
            "model": model_name,
            "rpm": rpm,
            "rpd": rpd,
        }
    
    def _get_model_daily_limit(self, model_name):
        """Get daily limit for the model."""
        # Try to get from API-fetched limits
        model_limits = self._hass.data.get(DOMAIN, {}).get("model_limits", {})
        if model_name in model_limits:
            return model_limits[model_name].get('rpd', 1500)
        
        # Fallback to hardcoded limits
        return MODEL_LIMITS_FALLBACK.get(model_name, {}).get('rpd', 1500)
    
    async def async_update(self):
        """Update the sensor."""
        pass
