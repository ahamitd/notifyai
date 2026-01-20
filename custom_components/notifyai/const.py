DOMAIN = "notifyai"
CONF_API_KEY = "api_key"
CONF_MODEL = "model"
CONF_NOTIFY_SERVICE_1 = "notify_service_1"
CONF_NOTIFY_SERVICE_2 = "notify_service_2"
CONF_NOTIFY_SERVICE_3 = "notify_service_3"
CONF_NOTIFY_SERVICE_4 = "notify_service_4"

MODEL_OPTIONS = {
    "gemini-2.5-flash": "Gemini 2.5 Flash (15 RPM, 1500/gün - Tahmini)",
    "gemini-2.5-pro": "Gemini 2.5 Pro (2 RPM, 50/gün - Tahmini)",
    "gemini-2.0-flash-exp": "Gemini 2.0 Flash Exp (10 RPM, 1000/gün - Tahmini)",
    "gemini-2.0-flash-lite-preview-02-05": "Gemini 2.0 Flash-Lite Preview (15 RPM, 1500/gün - Tahmini)",
    "gemini-1.5-flash": "Gemini 1.5 Flash (15 RPM, 1500/gün - Tahmini)",
    "gemini-1.5-pro": "Gemini 1.5 Pro (2 RPM, 50/gün - Tahmini)",
}

DEFAULT_MODEL = "gemini-2.5-flash"  # Highest RPM typically

# Fallback limits when API fetch fails
MODEL_LIMITS_FALLBACK = {
    "gemini-2.5-flash": {"rpm": 15, "rpd": 1500},
    "gemini-2.5-pro": {"rpm": 2, "rpd": 50},
    "gemini-2.0-flash-exp": {"rpm": 10, "rpd": 1000},
    "gemini-2.0-flash-lite-preview-02-05": {"rpm": 15, "rpd": 1500},
    "gemini-1.5-flash": {"rpm": 15, "rpd": 1500},
    "gemini-1.5-pro": {"rpm": 2, "rpd": 50},
}
