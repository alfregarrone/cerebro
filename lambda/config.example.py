# Copiá este archivo a `config.py` y completalo. `config.py` está en .gitignore:
# contiene tu clave y nunca debe subirse a un repositorio.

# Clave gratuita de Google AI Studio: https://aistudio.google.com/apikey
GEMINI_API_KEY = ""

# Modelos gratuitos que se consultan A LA VEZ; se usa la primera respuesta.
# (La velocidad de cada uno cambia mucho según la hora y Alexa corta a los ~8 segundos.)
# Cada entrada es (modelo, nivel de "thinking" o None).
MODELS = [
    ("gemini-3.6-flash", "minimal"),
    ("gemma-4-26b-a4b-it", None),        # más lento (~2,5 s) pero muy estable
    ("gemini-flash-lite-latest", None),
    ("gemini-3.5-flash-lite", "minimal"),
]
AI_TIMEOUT = 5.0   # segundos máximos esperando a Gemini

# Voz: vacío = la voz normal de Alexa.
VOICE = ""

# Para el clima y el resumen del día
CITY = "Buenos Aires"
LATITUDE = -34.6037
LONGITUDE = -58.3816
UTC_OFFSET_HOURS = -3

# Zona horaria para recordatorios
TIMEZONE_ID = "America/Argentina/Buenos_Aires"

# Búsqueda en Google: con la clave gratuita de Gemini NO está disponible (da error 429).
WEB_SEARCH = False

# Enlace privado con tu PC y tu celular, con la forma "topico:clave". Vacío = sin agente de PC.
# Generalo con:  python -c "import secrets; print(f'cerebro-{secrets.token_hex(10)}:{secrets.token_hex(24)}')"
# y poné el MISMO valor en el config del agente (pc/config.json).
CEREBRO_LINK = ""
