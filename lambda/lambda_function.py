"""Cerebro — Alexa custom skill backed by Google Gemini (free tier).

Capacidades: conversación, memoria permanente (DynamoDB de Alexa-hosted), recordatorios y temporizadores
de Alexa, y un puente con la PC del usuario (vía ntfy.sh, firmado con HMAC) para notas, control de la PC
y tareas con Claude Code.
"""
import hashlib
import hmac
import json
import logging
import os
import random
import re
import threading
import time
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime, timedelta, timezone
from xml.sax.saxutils import escape

import boto3
from ask_sdk_core.api_client import DefaultApiClient
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractExceptionHandler
from ask_sdk_core.skill_builder import CustomSkillBuilder
from ask_sdk_core.utils import is_request_type, is_intent_name
from ask_sdk_dynamodb.adapter import DynamoDbAdapter
from ask_sdk_model.ui import AskForPermissionsConsentCard
from ask_sdk_model.services.directive import SendDirectiveRequest, Header, SpeakDirective
from ask_sdk_model.interfaces.audioplayer import (
    PlayDirective, PlayBehavior, AudioItem, AudioItemMetadata, Stream, StopDirective,
)
from ask_sdk_model.services.reminder_management import (
    ReminderRequest, Trigger, TriggerType, AlertInfo, SpokenInfo, SpokenText,
    PushNotification, PushNotificationStatus, Recurrence,
)
from ask_sdk_model.services.timer_management import (
    TimerRequest, CreationBehavior, DisplayExperience, Visibility,
    TriggeringBehavior, NotifyOnlyOperation, NotificationConfig,
)

import config

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

REMINDERS_SCOPE = "alexa::alerts:reminders:skill:readwrite"
TIMERS_SCOPE = "alexa::alerts:timers:skill:readwrite"

MAX_SESSION_HISTORY = 12   # mensajes de la conversación actual
MAX_RECENT = 10            # mensajes que se recuerdan entre conversaciones
MAX_FACTS = 60             # datos permanentes sobre el usuario
ALEXA_BUDGET = 7.2         # segundos totales antes de que Alexa corte

GOODBYES = ("eso es todo", "eso es todo gracias", "nada más", "nada más gracias", "adiós", "chau",
            "basta", "listo gracias", "no gracias", "gracias eso es todo")
CALLS = ("cerebro", "oye cerebro", "hola cerebro", "estás ahí")
ACKS = ("¿Sí?", "Te escucho.", "Dime.")
YES = ("sí", "si", "confirmo", "sí confirmo", "si confirmo", "dale", "hazlo", "hacelo", "adelante", "ok", "okay",
       "claro", "sí por favor", "si por favor")
NO = ("no", "cancelar", "cancela", "cancelá", "mejor no", "no lo hagas")

# Acciones de la PC (las ejecuta pc/cerebro_pc.py)
PC_ACTIONS = {"nota", "buscar_notas", "pendientes", "completar_pendiente", "abrir_web", "abrir_app", "musica",
              "volumen", "sistema", "tarea", "confirmar_tarea", "estado", "info_pc", "avisar",
              "whatsapp", "whatsapp_confirmar", "whatsapp_leer",
              "casa", "casa_descubrir", "diagnostico", "frase", "recordar", "olvidar", "que_sabes", "whatsapp_editar", "aprender",
    "programar", "programados", "borrar_programado", "compras",
    "captura", "enviar_archivo", "cerrar_app", "tareas_estado", "cancelar_tarea",
    "whatsapp_resumen", "whatsapp_archivo", "alertas", "nombrar_aparato", "buscar_aparatos",
    "agenda", "mails", "salud_pc", "musica_control", "resumen_manana"}
PC_INFO_ACTIONS = {"que_sabes", "olvidar", "buscar_notas", "pendientes", "estado", "tarea", "confirmar_tarea", "completar_pendiente",
                   "info_pc", "whatsapp", "whatsapp_confirmar", "whatsapp_leer",
                   "casa", "casa_descubrir", "diagnostico", "whatsapp_editar", "aprender",
    "programar", "programados", "borrar_programado", "compras",
    "captura", "enviar_archivo", "cerrar_app", "tareas_estado", "cancelar_tarea",
    "whatsapp_resumen", "whatsapp_archivo", "alertas", "nombrar_aparato", "buscar_aparatos",
    "agenda", "mails", "salud_pc", "musica_control", "resumen_manana"}
PC_QUEUEABLE = {"nota", "completar_pendiente"}   # la PC las procesa al encenderse (hasta 12 h)
CONFIRM_ORDERS = {"apagar": "apagar", "reiniciar": "reiniciar", "suspender": "suspender"}

PERSONA = """Eres un asistente de voz que funciona dentro de un Amazon Echo, con el estilo de Alexa.

CÓMO HABLAS:
- Español neutro, tuteando al usuario. Amable, claro y directo, como Alexa.
- Sin personajes, sin apodos, sin humor ni ironía, sin exclamaciones exageradas.
- Primero la respuesta; solo agrega un detalle si realmente ayuda.
- Tu respuesta se lee en voz alta: normalmente 1 o 2 frases cortas; más solo si te piden detalle.
- Sin markdown, listas, emojis, enlaces ni paréntesis. Escribe los números como se dicen.

CÓMO ENTIENDES:
- El usuario es de Argentina: habla con voseo y expresiones rioplatenses (poné, dale, che, fijate, un toque,
  la compu, el celu, mi vieja). Entiéndelo siempre.
- Lo que te llega es voz transcrita y puede venir con errores: interpreta por cómo suena y por el contexto de la
  charla. Si algo es ambiguo, elige lo más probable y hazlo, en vez de preguntar.
- Si el usuario te cuenta algo de él, o cómo llama a sus cosas o a sus personas ("mi vieja es Marta"), guárdalo
  con recordar aunque no te lo pida.
- Si te corrige ("no, eso no", "lo que quería era..."), usa aprender para no repetir el error.
{search_rule}
Nunca inventes datos: si no lo sabes, dilo.

PUEDES EJECUTAR ACCIONES. Si corresponde, al final de tu respuesta agrega UNA línea exactamente así:
ACCIONES: [lista JSON]

Acciones de Alexa:
- {{"tipo": "recordar", "dato": "..."}}  -> guardar un dato personal útil del usuario (nombres, gustos, datos fijos).
- {{"tipo": "olvidar", "dato": "..."}}   -> borrar datos guardados que contengan ese texto.
- {{"tipo": "recordatorio", "texto": "...", "en_minutos": N}}  o  {{"tipo": "recordatorio", "texto": "...", "fecha_hora": "AAAA-MM-DDTHH:MM:SS"}}  (hora local)
- {{"tipo": "temporizador", "segundos": N, "etiqueta": "..."}}
- {{"tipo": "avisar_celular", "texto": "..."}}  -> mandar un texto al celular del usuario (listas, recetas, datos largos).
- {{"tipo": "terminar"}}  -> cuando el usuario se despide o dice que no necesita nada más.
- Recordatorio que SE REPITE en el Echo: agrega "repetir" al recordatorio:
  {{"tipo": "recordatorio", "texto": "...", "repetir": {{"frecuencia": "diaria" | "semanal" | "cada_horas",
  "hora": "HH:MM", "dias": ["lunes", "jueves"], "cada_horas": N, "desde": "HH:MM", "hasta": "HH:MM"}}}}
  ("todos los días a las 9", "los lunes a las 8", "cada 2 horas de 9 a 21"). Una alarma ("despertame a las 7")
  es un recordatorio con fecha_hora.
- {{"tipo": "recordatorios"}}  -> leer los recordatorios que tiene.
- {{"tipo": "borrar_recordatorio", "texto": "palabra del recordatorio" | "todos"}}
- {{"tipo": "clima", "ciudad": "..." (vacío = {city}), "dia": 0 hoy, 1 mañana, hasta 6}}  Para "el finde" agrega
  dos acciones clima: sábado y domingo.
- {{"tipo": "dolar"}}  -> cotización del dólar en Argentina (oficial, blue, MEP, tarjeta).
- {{"tipo": "noticias", "tema": "..." (vacío = titulares del día)}}
- {{"tipo": "radio", "nombre": "..."}}  -> poner una radio en vivo en el Echo ("Mitre", "La 100", "Rock and Pop").
- {{"tipo": "futbol", "equipo": "..." (vacío = partidos de la fecha)}}  -> resultados y próximos partidos
  (Liga Profesional, Libertadores y Sudamericana).
- {{"tipo": "cotizacion", "moneda": "euro" | "real" | "peso chileno" | "peso uruguayo" | "bitcoin" | "ethereum"}}
- {{"tipo": "temporizadores"}}  -> cuánto les falta.   {{"tipo": "cancelar_temporizador"}}
- {{"tipo": "argentina", "dato": "feriado" | "riesgo_pais" | "inflacion"}}
- {{"tipo": "convertir", "texto": "cuántos pesos son 100 dólares"}}  -> conversiones entre pesos, dólares, euros y
  reales (escribe el pedido así, con el número en cifras).
Para leer recordatorios, borrarlos, clima, dólar, noticias, fútbol, cotizaciones, temporizadores, feriados y conversiones tu frase debe ser mínima ("Un momento."), porque el
resultado se agrega después.

Acciones en la PC del usuario, con {{"tipo": "pc", "accion": "...", "datos": {{...}}}}:
- "nota" {{"texto": "...", "categoria": "idea" | "nota" | "pendiente"}}  -> segundo cerebro: guardar ideas, notas y pendientes.
- "buscar_notas" {{"consulta": "..."}}  -> buscar en sus notas ("¿qué anoté sobre...?").
- "pendientes" {{}}  -> leer los pendientes.
- "completar_pendiente" {{"texto": "..."}}  -> marcar un pendiente como hecho.
- "abrir_web" {{"url": "..."}} o {{"busqueda": "..."}}
- "abrir_app" {{"nombre": "..."}}
- "musica" {{"busqueda": "...", "servicio": "youtube" | "spotify"}}
- "volumen" {{"cambio": "subir" | "bajar" | "silenciar", "pasos": N}}  (cada paso es 2 por ciento)
- "sistema" {{"orden": "bloquear" | "suspender" | "apagar" | "reiniciar" | "cancelar_apagado"}}
- "tarea" {{"instruccion": "...", "modo": "consulta" | "cambios"}}  -> trabajo largo que hace Claude en la PC.
  Usa "consulta" para investigar, resumir o analizar sin tocar archivos. Usa "cambios" si hay que crear, mover,
  renombrar u ordenar archivos: primero se prepara un plan y el usuario lo aprueba.
- "confirmar_tarea" {{}}  -> cuando el usuario aprueba el plan pendiente ("confirma la tarea", "aprueba el plan").
- "estado" {{}}  -> saber si la PC está conectada.
- "casa" {{"dispositivo": "...", "accion": "prender" | "apagar" | "estado" | "brillo" | "color" |
  "temperatura" | "escena", "valor": ...}}  -> brillo lleva un número del 1 al 100; color lleva el nombre
  ("azul", "rojo", "violeta"); temperatura lleva "cálida", "neutra" o "fría"; escena lleva el nombre
  ("fiesta", "relax", "atardecer", "película", "navidad", "concentración", "bosque", "chimenea").
  -> luces y enchufes de la casa. Primero prueba por la red local (Philips WiZ y TP-Link, instantáneo);
  si el dispositivo es de otra marca, lo intenta solo por la app de Alexa de la PC y avisa al celular.
  Úsala para cualquier luz, enchufe o dispositivo del hogar.
- "casa_descubrir" {{}}  -> buscar qué dispositivos hay en la red y mandar la lista al celular.
- "diagnostico" {{}}  -> cuando algo falló y el usuario pregunta qué pasó: manda el registro al celular.
- "frase" {{"texto": "lo que dijo el usuario"}}  -> cuando pide algo de la casa o de la PC que no encaja
  en ninguna acción de arriba. La PC revisa si es una frase que el usuario le enseñó ("modo cine") y la ejecuta.
- "info_pc" {{}}  -> hora exacta de la PC, espacio libre en disco, nombre del equipo.
- "whatsapp" {{"contacto": "...", "mensaje": "..."}}  -> preparar un mensaje de WhatsApp. El sistema le lee al
  usuario a quién y qué va a mandar y pide la confirmación; tú NO preguntes, solo agrega la acción.
- "whatsapp_leer" {{"contacto": "..."}}  -> leer y resumir un chat de WhatsApp ("qué me escribió Laura"). Llega al
  celular.
- "programar" {{"texto": "...", "tipo": "aviso" | "orden", "cada_minutos": N, "cada_horas": N, "hora": "HH:MM",
  "dias": ["lunes"], "desde": "HH:MM", "hasta": "HH:MM", "en_minutos": N}}  -> avisos AL CELULAR por Telegram
  (cuando pide que le avise al celular, o cada pocos minutos) y RUTINAS: con "tipo": "orden" la PC ejecuta
  "texto" a esa hora ("todos los días a las 7 prendé la luz" -> texto "prendé la luz").
- "programados" {{}}  -> qué avisos y rutinas tiene.   "borrar_programado" {{"texto": "..." | "todos"}}
- "compras" {{"agregar": ["leche", "pan"]}} | {{"quitar": ["pan"]}} | {{"vaciar": true}} | {{}} para leerla;
  agrega "al_celular": true si quiere la lista en el celular.
- "captura" {{}}  -> mandarle al celular una foto de la pantalla de la PC.
- "enviar_archivo" {{"nombre": "..."}}  -> buscar un archivo en la PC y mandárselo al celular.
- "cerrar_app" {{"nombre": "..."}}  -> cerrar un programa abierto en la PC.
- "tareas_estado" {{}}  -> qué está haciendo la PC.   "cancelar_tarea" {{}}  -> frenar la tarea en curso.
- "whatsapp_resumen" {{}}  -> resumir los chats de WhatsApp sin leer ("qué mensajes tengo"). Llega al celular.
- "whatsapp_archivo" {{"contacto": "...", "archivo": "nombre del archivo", "mensaje": "comentario opcional"}}  -> mandar
  un archivo o foto de la PC por WhatsApp. El sistema pide la confirmación; tú NO preguntes.
- "alertas" {{"tipo": "dolar" | "lluvia" | "pc" | "mails" | "agenda" | "todas", "activar": true | false}}  -> prender
  o apagar los avisos automáticos (dólar, lluvia, problemas de la PC, mails importantes, eventos de la agenda); sin
  "activar" = decir cómo están.
- "nombrar_aparato" {{"aparato": "...", "nombre": "..."}}  -> ponerle nombre a una luz o aparato de la casa.
- "buscar_aparatos" {{}}  -> buscar aparatos nuevos en la casa.
- "agenda" {{"cuando": "hoy" | "mañana" | "el viernes" | "semana"}}  -> qué tiene en su Google Calendar. No puede
  agregar eventos: si quiere que le avisen de algo, usa un recordatorio.
- "mails" {{"voz": true}}  -> cuántos mails sin leer tiene y de quién (el resumen completo le llega al celular).
- "salud_pc" {{}}  -> cómo está la PC: disco, memoria, procesador, internet.
- "musica_control" {{"accion": "pausa" | "seguir" | "siguiente" | "anterior" | "que_suena"}}  -> controlar la
  música que suena en la PC.
- "resumen_manana" {{"hora": "HH:MM", "activar": true | false, "dias": "todos" | "semana", "equipo": "..."}}  ->
  configurar el resumen del día que le llega al celular cada mañana.
- "whatsapp_editar" {{"contacto": "...", "mensaje": "texto nuevo"}}  -> corregir el último mensaje que el usuario
  mandó en ese chat ("corregí el mensaje a Juan, que diga..."). Igual que whatsapp: tú NO preguntes.
- "aprender" {{"frase": "...", "pasos": ["...", "..."]}}  -> cuando el usuario te corrige o te explica qué quería
  ("no, eso no", "te dije que...", "lo que quería era..."). "frase" es su pedido ANTERIOR tal cual (míralo en la
  charla); "pasos" son órdenes cortas en español como "poné la luz al 20", "poné la luz roja", "prendé la luz".
  La PC hace lo correcto y lo guarda como lección (no como atajo fijo). Responde solo "Entendido.".
  Las lecciones aparecen en tu memoria como "Cuando el usuario dice...": tenlas en cuenta, pero entiende cada
  pedido completo; si pide algo distinto, haz lo que pide ahora.
- "tarea" con "modo": "pantalla"  -> cuando haya que manejar la pantalla: abrir una app y navegar por ella,
  hacer clics, completar formularios o usar una web. Trabaja sola y avisa al celular al terminar.
Para "buscar_notas", "pendientes", "tarea", "confirmar_tarea", "estado", "info_pc", "agenda", "mails", "salud_pc" y
"musica_control", tu frase debe ser mínima (por ejemplo
"Un momento."), porque el resultado real se agrega después. Para apagar, reiniciar o suspender, NO preguntes tú:
agrega la acción directamente y el sistema pedirá la confirmación.

Si lo puedes contestar tú (charla, ideas, recetas, cuentas, consejos, explicaciones, listas, traducciones),
contesta directamente y SIN acciones. NUNCA digas que algo no está habilitado o que no puedes: si hace falta trabajar
en la PC (archivos, programas, investigar en internet, manejar la pantalla), usa una "tarea".

REGLA ESTRICTA: si dices que hiciste algo, la línea ACCIONES con esa acción es OBLIGATORIA; sin ella nada ocurre.
Si no hay acciones, no agregues esa línea.

Ejemplos:
Usuario: recordame tomar agua cada dos horas
Asistente: Listo, te recuerdo tomar agua cada dos horas, de ocho de la mañana a diez de la noche.
ACCIONES: [{{"tipo": "recordatorio", "texto": "Tomar agua", "repetir": {{"frecuencia": "cada_horas", "cada_horas": 2, "desde": "08:00", "hasta": "22:00"}}}}]
Usuario: todos los lunes a las nueve recordame la reunión de equipo
Asistente: Listo, todos los lunes a las nueve te recuerdo la reunión de equipo.
ACCIONES: [{{"tipo": "recordatorio", "texto": "Reunión de equipo", "repetir": {{"frecuencia": "semanal", "dias": ["lunes"], "hora": "09:00"}}}}]
Usuario: avisame al celular cada media hora que me estire
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "programar", "datos": {{"texto": "Estirarte", "tipo": "aviso", "cada_minutos": 30}}}}]
Usuario: de lunes a viernes a las siete de la mañana prendé la luz
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "programar", "datos": {{"texto": "prendé la luz", "tipo": "orden", "hora": "07:00", "dias": ["lunes", "martes", "miércoles", "jueves", "viernes"]}}}}]
Usuario: agregá leche y huevos a la lista de compras
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "compras", "datos": {{"agregar": ["leche", "huevos"]}}}}]
Usuario: cómo va a estar el clima el sábado en Mar del Plata
Asistente: Un momento.
ACCIONES: [{{"tipo": "clima", "ciudad": "Mar del Plata", "dia": 3}}]
Usuario: pon un temporizador de diez minutos para el horno
Asistente: Listo, temporizador de diez minutos para el horno.
ACCIONES: [{{"tipo": "temporizador", "segundos": 600, "etiqueta": "horno"}}]
Usuario: anota la idea de hacer un video sobre ahorro
Asistente: Anoté tu idea.
ACCIONES: [{{"tipo": "pc", "accion": "nota", "datos": {{"texto": "Hacer un video sobre ahorro", "categoria": "idea"}}}}]
Usuario: qué pendientes tengo
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "pendientes", "datos": {{}}}}]
Usuario: prendé la luz del living
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "casa", "datos": {{"dispositivo": "luz living", "accion": "prender"}}}}]
Usuario: poné la luz azul
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "casa", "datos": {{"dispositivo": "luz", "accion": "color", "valor": "azul"}}}}]
Usuario: poné modo fiesta
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "casa", "datos": {{"dispositivo": "luz", "accion": "escena", "valor": "fiesta"}}}}]
Usuario: poné la luz del living al treinta por ciento
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "casa", "datos": {{"dispositivo": "luz living", "accion": "brillo", "valor": 30}}}}]
Usuario: apaga la computadora
Asistente: De acuerdo.
ACCIONES: [{{"tipo": "pc", "accion": "sistema", "datos": {{"orden": "apagar"}}}}]
Usuario: mandale un whatsapp a Juan diciendo que llego en veinte minutos
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "whatsapp", "datos": {{"contacto": "Juan", "mensaje": "Llego en veinte minutos"}}}}]
Usuario: corregí el mensaje que le mandé a Juan, que diga llego en media hora
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "whatsapp_editar", "datos": {{"contacto": "Juan", "mensaje": "Llego en media hora"}}}}]
Usuario: no, cuando digo modo cine quiero la luz baja y en rojo
Asistente: Entendido.
ACCIONES: [{{"tipo": "pc", "accion": "aprender", "datos": {{"frase": "modo cine", "pasos": ["poné la luz al 20", "poné la luz roja"]}}}}]
Usuario: no, lo que quería era la luz cálida al 50
Asistente: Entendido.
ACCIONES: [{{"tipo": "pc", "accion": "aprender", "datos": {{"frase": "", "pasos": ["luz cálida", "poné la luz al 50"]}}}}]
Usuario: qué me escribió Laura
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "whatsapp_leer", "datos": {{"contacto": "Laura"}}}}]
Usuario: abrí el navegador y buscá el clima de Córdoba
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "tarea", "datos": {{"instruccion": "Abrir el navegador y buscar el clima de Córdoba", "modo": "pantalla"}}}}]
Usuario: investiga las mejores estrategias para retener usuarios en una app de finanzas
Asistente: Un momento.
ACCIONES: [{{"tipo": "pc", "accion": "tarea", "datos": {{"instruccion": "Investigar las mejores estrategias para retener usuarios en una app de finanzas personales y resumirlas", "modo": "consulta"}}}}]

CONTEXTO DE AHORA
Fecha y hora actual: {now} ({city}).

Lo que recuerdas del usuario (memoria permanente):
{facts}

Lo último que hablaron en conversaciones anteriores:
{recent}"""


# ---------- helpers ----------

def now_local():
    return datetime.now(timezone(timedelta(hours=config.UTC_OFFSET_HOURS)))


def say(text):
    voice = getattr(config, "VOICE", "")
    if not voice:
        return escape(text)   # voz normal de Alexa
    return f'<voice name="{voice}">{escape(text)}</voice>'


def build_system_prompt(facts, recent):
    n = now_local()
    return PERSONA.format(
        now=n.strftime("%Y-%m-%d %H:%M, %A"),
        city=config.CITY,
        search_rule=("Si te preguntan algo actual (noticias, resultados, precios), busca en Google."
                     if config.WEB_SEARCH else
                     "Datos en vivo: usa las acciones clima, dolar y noticias. Para otros datos actuales (resultados "
                     "deportivos, precios, horarios), usa una tarea de consulta en la PC y di que la respuesta le llega "
                     "al celular."),
        facts="\n".join(f"- {f}" for f in facts) or "(nada todavía)",
        recent="\n".join(f"{'Usuario' if m['role'] == 'user' else 'Asistente'}: {m['content']}" for m in recent) or "(nada)",
    )


PRIMEROS_IA = ("gemini-flash-lite-latest", "gemma-4-26b-a4b-it")
_AGOTADOS = {}      # modelo -> hasta cuándo no llamarlo (se quedó sin cupo o está saturado)


def _gemini_call(model, thinking, payload, timeout):
    gen = dict(payload["generationConfig"])
    if thinking:
        gen["thinkingConfig"] = {"thinkingLevel": thinking}
    body = json.dumps({**payload, "generationConfig": gen}).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={"x-goog-api-key": config.GEMINI_API_KEY, "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as e:
        if e.code == 429:            # sin cupo (por minuto o por día): no insistir por un rato
            _AGOTADOS[model] = time.time() + (3600 if "PerDay" in e.read().decode(errors="ignore") else 30)
        elif e.code in (500, 503):   # saturado
            _AGOTADOS[model] = time.time() + 60
        raise
    parts = data["candidates"][0]["content"].get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
    if not text:
        raise ValueError(f"{model}: respuesta vacía")
    return text


def ask_ai(system, messages, max_tokens=400, search=None, timeout=None):
    """Call Google Gemini (free tier). messages: [{"role": "user"|"assistant", "content": str}]

    The free models' latency swings a lot during the day, and Alexa cuts off at ~8s, so we ask
    several models at once and keep the first good answer.
    """
    timeout = timeout or config.AI_TIMEOUT
    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
        ],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.3},
    }
    if config.WEB_SEARCH if search is None else search:
        payload["tools"] = [{"google_search": {}}]

    # Por tandas: primero los que tienen más cupo gratis y contestan rápido; los demás solo si esos fallan o tardan.
    modelos = [m for m in config.MODELS if _AGOTADOS.get(m[0], 0) < time.time()] or list(config.MODELS)
    primeros = [m for m in modelos if m[0] in PRIMEROS_IA] or modelos[:2]
    despues = [m for m in modelos if m not in primeros]
    pool = ThreadPoolExecutor(max_workers=len(config.MODELS))
    pendientes = {pool.submit(_gemini_call, model, thinking, payload, timeout) for model, thinking in primeros}
    last_error = TimeoutError("sin respuesta de Gemini")
    limite = time.time() + timeout + 0.2
    segunda = time.time() + 1.8
    try:
        while pendientes or despues:
            if despues and (not pendientes or time.time() >= segunda):
                pendientes |= {pool.submit(_gemini_call, model, thinking, payload, timeout) for model, thinking in despues}
                despues = []
            espera = (min(limite, segunda) if despues else limite) - time.time()
            if espera <= 0 and not despues:
                break
            listos, pendientes = wait(pendientes, timeout=max(0.05, espera), return_when=FIRST_COMPLETED)
            for future in listos:
                try:
                    return future.result()
                except Exception as e:
                    logger.warning("gemini model failed: %s", e)
                    last_error = e
            if time.time() >= limite:
                break
    finally:
        try:
            pool.shutdown(wait=False, cancel_futures=True)
        except TypeError:  # Python < 3.9
            pool.shutdown(wait=False)
    raise last_error


ACTIONS_RE = re.compile(r"ACCIONES:\s*(\[.*\])", re.S)


def split_actions(text):
    """Separate the spoken answer from the trailing ACCIONES JSON."""
    m = ACTIONS_RE.search(text)
    if not m:
        return text.replace("ACCIONES:", "").strip(), []
    speech = text[:m.start()].strip()
    try:
        actions = json.loads(m.group(1))
        if not isinstance(actions, list):
            actions = []
    except ValueError:
        logger.warning("bad actions json: %s", m.group(1))
        actions = []
    return speech, [a for a in actions if isinstance(a, dict)]


def get_weather(timeout=2.0):
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={config.LATITUDE}&longitude={config.LONGITUDE}"
        "&current=temperature_2m,weather_code,wind_speed_10m"
        "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        "&timezone=auto&forecast_days=1"
    )
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            d = json.load(resp)
        c, day = d["current"], d["daily"]
        return (
            f"ahora {c['temperature_2m']}°C (código WMO {c['weather_code']}), viento {c['wind_speed_10m']} km/h; "
            f"hoy mínima {day['temperature_2m_min'][0]}°C, máxima {day['temperature_2m_max'][0]}°C, "
            f"probabilidad de lluvia {day['precipitation_probability_max'][0]}%"
        )
    except Exception as e:  # weather is optional
        logger.warning("weather failed: %s", e)
        return "sin datos de clima"


def has_permission(handler_input, scope):
    user = handler_input.request_envelope.context.system.user
    perms = user.permissions
    if not perms or not perms.consent_token:
        return False
    scopes = getattr(perms, "scopes", None) or {}
    status = scopes.get(scope)
    # Si Alexa no informa scopes, intentamos igual con el token.
    return status is None or str(getattr(status, "status", "GRANTED")).endswith("GRANTED")


# ---------- puente con la PC (ntfy.sh + HMAC) ----------

def pc_link():
    link = getattr(config, "CEREBRO_LINK", "")
    if ":" not in link:
        return None, None
    topic, secret = link.split(":", 1)
    return topic.strip(), secret.strip()


def _sign(secret, text):
    return hmac.new(secret.encode(), text.encode(), hashlib.sha256).hexdigest()


def ntfy_publish(topic, text, title=None, timeout=2.0):
    headers = {"Title": title} if title else {}
    req = urllib.request.Request(f"https://ntfy.sh/{topic}", data=text.encode("utf-8"), headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resp.read()




def send_to_pc(accion, datos, wait):
    """Send a signed order to the PC and wait up to `wait` seconds for its signed reply.

    Returns the reply dict, or None if the PC did not answer in time.
    """
    topic, secret = pc_link()
    msg = {"id": uuid.uuid4().hex[:16], "ts": int(time.time()), "accion": accion, "datos": datos}
    msg["firma"] = _sign(secret, f'{msg["id"]}|{msg["ts"]}|{accion}|{json.dumps(datos, sort_keys=True, ensure_ascii=False)}')

    deadline = time.time() + wait
    # Publicar y abrir el canal de respuesta tardan medio segundo cada uno: los hacemos a la vez.
    envio = ThreadPoolExecutor(max_workers=1)
    publicado = envio.submit(ntfy_publish, topic, json.dumps(msg, ensure_ascii=False))
    try:
        with urllib.request.urlopen(f"https://ntfy.sh/{topic}-r/json", timeout=wait) as stream:
            stream.readline()  # evento "open"
            publicado.result(timeout=max(0.5, deadline - time.time()))
            while time.time() < deadline:
                line = stream.readline()
                if not line:
                    break
                try:
                    reply = json.loads(json.loads(line).get("message", ""))
                except (ValueError, AttributeError):
                    continue
                if not isinstance(reply, dict) or reply.get("id") != msg["id"]:
                    continue
                expected = _sign(secret, f'{reply["id"]}|{reply.get("ok")}|{reply.get("texto", "")}')
                if hmac.compare_digest(expected, str(reply.get("firma", ""))):
                    return reply
    except Exception as e:  # timeout o red: la PC no respondió a tiempo
        logger.warning("pc wait ended: %s", e)
    finally:
        envio.shutdown(wait=False)
    return None


def notify_phone(text):
    """Avisa al celular. Lo manda la PC (Telegram); si no responde, va por ntfy."""
    topic, _ = pc_link()
    if not topic:
        return False
    try:
        return bool(send_to_pc("avisar", {"texto": text[:3500]}, wait=2.5))
    except Exception as e:
        logger.warning("aviso por la PC falló: %s", e)
        return False
def send_to_pc_async(accion, datos):
    """Manda una orden a la PC sin esperar respuesta: sirve para sincronizar la memoria."""
    topic, secret = pc_link()
    if not topic:
        return
    msg = {"id": uuid.uuid4().hex[:16], "ts": int(time.time()), "accion": accion, "datos": datos}
    msg["firma"] = _sign(secret, f'{msg["id"]}|{msg["ts"]}|{accion}|{json.dumps(datos, sort_keys=True, ensure_ascii=False)}')
    try:
        ntfy_publish(topic, json.dumps(msg, ensure_ascii=False), timeout=1.5)
    except Exception as e:
        logger.warning("no pude sincronizar con la PC: %s", e)


def run_pc_action(a, deadline):
    """Returns (kind, text): kind is 'ok', 'info' (append to speech) or 'problem' (replace speech)."""
    accion = str(a.get("accion") or "")
    datos = a.get("datos") if isinstance(a.get("datos"), dict) else {}
    if accion not in PC_ACTIONS:
        return "problem", "No sé hacer eso en tu PC."
    if not pc_link()[0]:
        return "problem", "La conexión con tu PC todavía no está configurada."
    reply = send_to_pc(accion, datos, wait=max(1.0, min(4.5, deadline - time.time())))
    if reply is None:
        if accion in PC_QUEUEABLE:
            return "info", "Tu PC no respondió; se va a guardar cuando la enciendas."
        return "problem", "No pude comunicarme con tu PC. Verifica que esté encendida y con Cerebro en ejecución."
    if not reply.get("ok"):
        return "problem", reply.get("texto") or "Tu PC no pudo completar esa acción."
    if accion in PC_INFO_ACTIONS:
        return "info", reply.get("texto", "")
    return "ok", ""


# ---------- actions ----------

COLORES_RAPIDOS = ("rojo", "verde", "azul", "amarillo", "naranja", "violeta", "morado", "lila", "rosa",
                   "rosado", "celeste", "turquesa", "blanco", "dorado", "coral", "fucsia", "menta", "bordo")

ESCENAS_RAPIDAS = ("fiesta", "relax", "romance", "oceano", "atardecer", "bosque", "selva", "chimenea",
                   "velas", "acogedor", "concentracion", "dormir", "noche", "despertar", "tele",
                   "television", "pelicula", "navidad", "halloween", "boliche", "club", "arcoiris",
                   "pastel", "mojito", "ritmo", "primavera", "verano", "otono")


def _sin_tildes(texto):
    reemplazos = (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ü", "u"))
    texto = texto.lower()
    for a, b in reemplazos:
        texto = texto.replace(a, b)
    return texto


AGENDA_VOZ = (r"(que|q) (tengo|hay)( en (la|mi) agenda)?( para)?( (hoy|manana|pasado manana|esta semana|la semana|"
              r"el (lunes|martes|miercoles|jueves|viernes|sabado|domingo)))( en (la|mi) agenda)?$|(mi |la )?agenda"
              r"( de| para)?( (hoy|manana|pasado manana|la semana|esta semana|el \w+))?$|tengo algo( para)? (hoy|"
              r"manana|pasado manana|el \w+)$")
MAILS_VOZ = (r"(tengo )?(algun )?(mails?|correos?|e-?mails?)( nuevos?| sin leer)?$|(que|q) (mails|correos) tengo$|"
             r"(revisa|revisame|resumi|resumime|lee|leeme|chequea|fijate)( el| los| mi| mis)? (mail|mails|correo|"
             r"correos|e-?mails?|gmail)$|me (llego|llegaron) (algun |mails|correos|mail|correo)")
SALUD_VOZ = (r"(como (esta|anda|va) la (pc|compu|computadora|maquina)|salud de la (pc|compu)|esta bien la (pc|compu)|"
             r"cuanto espacio (libre )?(queda|hay|tiene|me queda)( en)?( el disco| la pc| la compu)?)$|"
             r"cuanto (espacio|lugar)\b.*\b(disco|pc|compu|computadora)\b")
MUSICA_VOZ = (
    (r"(pausa|pausala|pausa la musica|pone pausa|para la musica|frena la musica|deten la musica|parala)$", "pausa"),
    (r"(segui|reanuda|reanudala|continua|continua la musica|dale play|pone play|segui con la musica|"
     r"volve a poner la musica|pone la musica de nuevo)$", "seguir"),
    (r"(siguiente|siguiente tema|siguiente cancion|pasala|otro tema|otra cancion|cambiala|salteala)$|"
     r"(pasa|pasame|salta|saltea|cambia|cambiame)( este| ese| el| la| de| al)? (tema|cancion|siguiente)\b", "siguiente"),
    (r"(anterior|tema anterior|cancion anterior|volve al tema anterior|la anterior|volve un tema)$", "anterior"),
    (r"(que (esta sonando|suena|tema es este|tema es esto|cancion es esta|cancion es esto|estoy escuchando|"
     r"musica esta sonando)|como se llama (este tema|esta cancion))$", "que_suena"),
)


def via_rapida(frase):
    """Comandos de todos los días: los resolvemos sin preguntarle a la IA (ahorra ~1,7 s).

    Devuelve (accion, datos, respuesta_hablada) o None si hay que pensarlo.
    """
    t = _sin_tildes(frase).strip(" .!?¡¿,")
    if t.startswith(("no ", "no,", "cuando ")) or "queria" in t or "quise" in t:
        return None     # es una corrección o una explicación: la piensa la IA para aprenderla

    # luces: prender y apagar
    for verbo, accion, dicho in (("prende", "prender", "Listo"), ("encende", "prender", "Listo"),
                                 ("apaga", "apagar", "Listo")):
        if t.startswith(verbo):
            resto = t[len(verbo):].strip()
            for basura in ("la ", "el ", "las ", "los "):
                if resto.startswith(basura):
                    resto = resto[len(basura):]
            return "casa", {"dispositivo": resto or "luz", "accion": accion}, dicho

    hay_luz = "luz" in t or "luces" in t or "lampara" in t
    if hay_luz and re.search(r"\b(esta|estan|quedo|quedaron|sigue|siguen)\s+(prendid|encendid|apagad)|^como (esta|estan) la", t):
        m = re.search(r"\b(?:la|las|el)\s+((?:luz|luces|lampara)(?:\s+del?\s+\w+)?)", t)
        return "casa", {"dispositivo": m.group(1) if m else "luz", "accion": "estado"}, "No pude leer la luz."
    if hay_luz:
        # color
        for color in COLORES_RAPIDOS:
            if color in t or (color.endswith("o") and color[:-1] + "a" in t):
                return "casa", {"dispositivo": "luz", "accion": "color", "valor": color}, "Listo"
        # brillo: "al 30", "30 por ciento"
        numeros = re.findall(r"\d{1,3}", t)
        if numeros and ("al " in t or "por ciento" in t or "brillo" in t or "%" in frase):
            return "casa", {"dispositivo": "luz", "accion": "brillo", "valor": int(numeros[-1])}, "Listo"
        # más o menos luz
        if any(x in t for x in ("baja", "menos luz", "mas tenue", "tenue", "bajale")):
            return "casa", {"dispositivo": "luz", "accion": "brillo", "valor": 30}, "Listo"
        if any(x in t for x in ("subi", "sube", "mas luz", "a full", "al maximo", "subile")):
            return "casa", {"dispositivo": "luz", "accion": "brillo", "valor": 100}, "Listo"
        # temperatura
        for palabra, valor in (("calida", "cálida"), ("calido", "cálida"), ("fria", "fría"),
                               ("frio", "fría"), ("neutra", "neutra")):
            if palabra in t:
                return "casa", {"dispositivo": "luz", "accion": "temperatura", "valor": valor}, "Listo"

    # escenas: "modo fiesta", "escena relax"
    if t.startswith(("modo ", "escena ", "pone modo ", "pone escena ")):
        pedido = t.split(" ", 1)[1].replace("escena ", "").replace("modo ", "").strip()
        if pedido:      # la PC se fija primero si es una frase que le enseñaste ("modo cine")
            return "frase", {"texto": frase}, "Listo"

    # lista de compras y avisos
    if re.match(r"^(que hay en |leeme |decime |que tengo en |mostrame )?(la |mi )?lista( de compras| del super)?$", t) \
            or t in ("que tengo que comprar", "que falta comprar"):
        return "compras", {}, ""
    m = re.match(r"^(agrega|agregame|agregar|suma|sumale|anota|anotame|pone|poneme)\s+(.+?)\s+(a|en)\s+(la\s+|mi\s+)?"
                 r"lista(\s+de\s+compras|\s+del\s+super)?$", t)
    if m:
        items = [x.strip() for x in re.split(r",\s*|\s+y\s+", m.group(2)) if x.strip()]
        return "compras", {"agregar": items}, "Agregado"
    if t in ("que avisos tengo", "mis avisos", "que tengo programado", "que avisos tengo programados",
             "que rutinas tengo", "mis rutinas", "que avisos hay"):
        return "programados", {}, ""
    if t in ("que estas haciendo", "como va la tarea", "estado de la tarea", "en que andas", "que hace la pc"):
        return "tareas_estado", {}, ""
    if t.startswith(("cancela la tarea", "frena la tarea", "para la tarea", "cancela todo", "frena todo")):
        return "cancelar_tarea", {}, ""
    if t in ("mandame la pantalla", "mandame una captura", "sacale foto a la pantalla", "captura de pantalla",
             "mandame una captura de pantalla"):
        return "captura", {}, ""
    if t in ("que mensajes tengo", "tengo mensajes", "mensajes nuevos", "que me escribieron", "resumime whatsapp",
             "mensajes sin leer", "que hay en whatsapp", "tengo mensajes nuevos", "novedades de whatsapp"):
        return "whatsapp_resumen", {}, ""
    if re.match(AGENDA_VOZ, t.replace("ñ", "n")) and not re.match(r"(que|q) (tengo|hay)$", t):
        return "agenda", {"cuando": t}, ""
    if re.match(MAILS_VOZ, t.replace("ñ", "n")):
        return "mails", {"voz": True}, ""
    if re.match(SALUD_VOZ, t):
        return "salud_pc", {}, ""
    for patron, que in MUSICA_VOZ:
        if re.match(patron, t):
            return "musica_control", {"accion": que}, ""
    if re.search(r"\bresumen\b", t) and re.search(r"\ba las\s+(\d|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|"
                                                   r"diez|once|doce)\b", t):
        dias = {"dias": "semana"} if re.search(r"lunes a viernes|dias de semana|dias habiles", t) else {}
        return "resumen_manana", {"hora": t.split("a las", 1)[1], **dias}, ""
    if re.search(r"\bresumen\b", t) and re.match(r"(desactiva|saca|apaga|frena|cancela|no me mandes)", t):
        return "resumen_manana", {"activar": False}, ""

    # volumen de la PC
    if "volumen" in t:
        n = re.findall(r"\d{1,3}", t)
        if n and ("al " in t or "en " in t):
            return "volumen", {"nivel": int(n[-1])}, "Listo"
        if any(x in t for x in ("subi", "sube", "subir", "mas alto", "aumenta")):
            return "volumen", {"cambio": "subir", "pasos": 5}, "Listo"
        if any(x in t for x in ("baja", "bajar", "mas bajo")):
            return "volumen", {"cambio": "bajar", "pasos": 5}, "Listo"
    if t in ("silencio", "silencia la pc", "mutea la pc", "silenciar la pc", "silencia la compu"):
        return "volumen", {"cambio": "silenciar"}, "Listo"

    # música en la PC: "poné música de Soda Stereo", "poné Ciro en spotify"
    m = re.match(r"(pone|poneme|reproduci|quiero escuchar)\s+(musica de |musica |la cancion |el tema |"
                 r"canciones de |algo de )?(.+?)(\s+en\s+(spotify|youtube))?$", t)
    if m and (m.group(2) or m.group(5)) and m.group(3).strip():
        return "musica", {"busqueda": m.group(3).strip(), "servicio": m.group(5) or "youtube"}, "Listo"

    # abrir programas o sitios: "abrí Chrome", "abrí YouTube"
    m = re.match(r"(abri|abre|abrime|abrir)\s+(el |la |los |las )?([\w .]+)$", t)
    if m and " y " not in t and len(m.group(3).split()) <= 3:
        nombre = m.group(3).strip()
        sitios = {"youtube": "youtube.com", "gmail": "mail.google.com", "netflix": "netflix.com",
                  "facebook": "facebook.com", "instagram": "instagram.com", "mercado libre": "mercadolibre.com.ar",
                  "google": "google.com", "twitter": "x.com", "chatgpt": "chatgpt.com"}
        if nombre in sitios or "." in nombre:
            return "abrir_web", {"url": sitios.get(nombre, nombre)}, "Listo"
        return "abrir_app", {"nombre": nombre}, "Listo"
    if t in ("bloquea la pc", "bloquea la compu", "bloquea la computadora", "bloquear la pc"):
        return "sistema", {"orden": "bloquear"}, "Listo"

    # notas y pendientes
    if t.startswith(("anota ", "anotar ", "anotame ")):
        texto = frase.split(" ", 1)[1].strip()
        if texto:
            return "nota", {"texto": texto, "categoria": "idea"}, "Anotado"
    if t.startswith(("agrega a pendientes ", "sumar a pendientes ", "pendiente ")):
        texto = frase.split("pendientes", 1)[-1].strip() if "pendientes" in t else frase.split(" ", 1)[1]
        if texto:
            return "nota", {"texto": texto.strip(": "), "categoria": "pendiente"}, "Agregado a pendientes"
    if t in ("pendientes", "que pendientes tengo", "mis pendientes", "cuales son mis pendientes",
             "decime mis pendientes", "leeme los pendientes"):
        return "pendientes", {}, ""

    # estado de la PC y memoria
    if t in ("estado de la pc", "como esta la pc", "que hora es en la pc", "cuanto espacio tiene la pc",
             "cuanto espacio libre tiene la pc", "espacio en disco"):
        return "info_pc", {}, ""
    if t in ("que sabes de mi", "que te acordas de mi", "que recordas de mi", "que guardaste de mi"):
        return "que_sabes", {}, ""

    return None


def run_actions(handler_input, actions, memory, deadline):
    """Execute model actions.

    Returns dict with: problems (replace speech), info (append to speech), missing (permissions),
    end (bool), confirm (question to ask; the action is stored as pending in the session).
    """
    out = {"problems": [], "info": [], "missing": [], "end": False, "confirm": None, "audio": None}
    session = handler_input.attributes_manager.session_attributes
    for a in actions:
        kind = a.get("tipo")
        try:
            if kind == "recordar" and a.get("dato"):
                dato = str(a["dato"]).strip()
                if dato not in memory["facts"]:
                    memory["facts"] = (memory["facts"] + [dato])[-MAX_FACTS:]
                send_to_pc_async("recordar", {"dato": dato})     # la PC guarda la misma memoria
            elif kind == "olvidar" and a.get("dato"):
                needle = str(a["dato"]).lower()
                memory["facts"] = [f for f in memory["facts"] if needle not in f.lower()]
                send_to_pc_async("olvidar", {"dato": needle})
            elif kind == "recordatorio":
                if not has_permission(handler_input, REMINDERS_SCOPE):
                    out["missing"].append(REMINDERS_SCOPE)
                    out["problems"].append("Para crear recordatorios necesito tu permiso. Te dejé una tarjeta en la app de Alexa.")
                    continue
                try:
                    create_reminder(handler_input, a)
                except Exception as e:
                    logger.exception("reminder failed: %s", e)
                    if not isinstance(a.get("repetir"), dict):
                        out["problems"].append("No pude crear el recordatorio.")
                        continue
                    # Alexa no lo aceptó: que lo avise la PC por Telegram
                    tipo, texto = run_pc_action({"accion": "programar", "datos": {
                        **a["repetir"], "texto": str(a.get("texto") or "Recordatorio"), "tipo": "aviso"}}, deadline)
                    out["problems"].append(texto if tipo == "problem" else
                                           "Alexa no me dejó repetirlo en el Echo. " + (texto or "Te aviso al celular."))
            elif kind == "temporizador":
                if not has_permission(handler_input, TIMERS_SCOPE):
                    out["missing"].append(TIMERS_SCOPE)
                    out["problems"].append("Para usar temporizadores necesito tu permiso. Te dejé una tarjeta en la app de Alexa.")
                    continue
                create_timer(handler_input, a)
            elif kind in ("recordatorios", "borrar_recordatorio"):
                if not has_permission(handler_input, REMINDERS_SCOPE):
                    out["missing"].append(REMINDERS_SCOPE)
                    out["problems"].append("Para ver tus recordatorios necesito tu permiso. Te dejé una tarjeta en la app de Alexa.")
                    continue
                out["info"].append(gestionar_recordatorios(handler_input, kind, a))
            elif kind in ("clima", "dolar", "noticias"):
                try:
                    out["info"].append(clima(a.get("ciudad"), a.get("dia", 0)) if kind == "clima" else
                                       dolar() if kind == "dolar" else noticias(str(a.get("tema") or "")))
                except Exception as e:
                    logger.warning("dato en vivo %s: %s", kind, e)
                    out["problems"].append("No pude conseguir ese dato ahora. Probá de nuevo en un rato.")
            elif kind in ("argentina", "convertir"):
                try:
                    if kind == "convertir":
                        r = convertir(_sin_tildes(str(a.get("texto") or "")).replace("ñ", "n").strip(" .!?¡¿,"))
                    else:
                        dato = _sin_tildes(str(a.get("dato") or ""))
                        r = riesgo_pais() if "riesgo" in dato else inflacion() if "infla" in dato else proximo_feriado()
                    out["info"].append(r or "No entendí qué convertir.")
                except Exception as e:
                    logger.warning("dato argentino %s: %s", kind, e)
                    out["problems"].append("No pude conseguir ese dato ahora. Probá de nuevo en un rato.")
            elif kind in ("futbol", "cotizacion"):
                try:
                    out["info"].append(futbol(str(a.get("equipo") or "")) if kind == "futbol"
                                       else cotizacion(str(a.get("moneda") or "")))
                except Exception as e:
                    logger.warning("dato en vivo %s: %s", kind, e)
                    out["problems"].append("No pude conseguir ese dato ahora. Probá de nuevo en un rato.")
            elif kind == "radio":
                radio = buscar_radio(str(a.get("nombre") or "")) if soporta_audio(handler_input) else None
                if radio:
                    out["audio"] = radio
                    memory["radio"] = list(radio)
                else:
                    out["problems"].append("No encontré esa radio para reproducir acá.")
            elif kind in ("temporizadores", "cancelar_temporizador"):
                if not has_permission(handler_input, TIMERS_SCOPE):
                    out["missing"].append(TIMERS_SCOPE)
                    out["problems"].append("Para usar temporizadores necesito tu permiso. Te dejé una tarjeta en la app de Alexa.")
                    continue
                out["info"].append(gestionar_temporizadores(handler_input, kind))
            elif kind == "avisar_celular" and a.get("texto"):
                if not notify_phone(str(a["texto"])):
                    out["problems"].append("La conexión con tu celular todavía no está configurada.")
            elif kind == "pc":
                orden = str((a.get("datos") or {}).get("orden", "")) if isinstance(a.get("datos"), dict) else ""
                if a.get("accion") == "sistema" and orden in CONFIRM_ORDERS and not a.get("_confirmado"):
                    session["pending"] = a
                    out["confirm"] = f"¿Confirmas que quieres {CONFIRM_ORDERS[orden]} la PC?"
                    continue
                if a.get("accion") in ("whatsapp", "whatsapp_editar", "whatsapp_archivo") and not a.get("_confirmado"):
                    result, text = run_pc_action(a, deadline)
                    if result == "problem":
                        out["problems"].append(text)
                    else:
                        session["pending"] = {"tipo": "pc", "accion": "whatsapp_confirmar", "datos": {},
                                              "_confirmado": True}
                        out["confirm"] = (text or "Preparé el mensaje.") + (
                            " ¿Lo corrijo?" if a.get("accion") == "whatsapp_editar" else " ¿Lo envío?")
                    continue
                result, text = run_pc_action(a, deadline)
                if result == "problem":
                    out["problems"].append(text)
                elif result == "info" and text:
                    out["info"].append(text)
                if a.get("accion") == "aprender" and result != "problem":
                    datos_ap = a.get("datos") or {}
                    frase_nueva = str(datos_ap.get("frase") or "").strip(" .!?¡¿,")
                    pasos_ap = datos_ap.get("pasos") or []
                    if frase_nueva and pasos_ap:
                        prefijo = f'Cuando el usuario dice "{frase_nueva}"'
                        pasos_txt = "; ".join(map(str, pasos_ap)) if isinstance(pasos_ap, list) else str(pasos_ap)
                        memory["facts"] = ([f for f in memory["facts"] if not f.startswith(prefijo)]
                                           + [f"{prefijo}, quiere: {pasos_txt}."])[-MAX_FACTS:]
            elif kind == "terminar":
                out["end"] = True
        except Exception as e:
            logger.exception("action %s failed: %s", kind, e)
            out["problems"].append("No pude completar esa acción.")
    return out


def create_reminder(handler_input, a):
    now = now_local()
    text = str(a.get("texto") or "Recordatorio")
    if isinstance(a.get("repetir"), dict):
        inicio = now_local().replace(tzinfo=None, microsecond=0) + timedelta(minutes=1)
        trigger = Trigger(object_type=TriggerType.SCHEDULED_ABSOLUTE, time_zone_id=config.TIMEZONE_ID,
                          recurrence=Recurrence(start_date_time=inicio,
                                                recurrence_rules=reglas_repeticion(a["repetir"])))
    elif a.get("fecha_hora"):
        trigger = Trigger(object_type=TriggerType.SCHEDULED_ABSOLUTE,
                          scheduled_time=str(a["fecha_hora"])[:19],
                          time_zone_id=config.TIMEZONE_ID)
    else:
        seconds = max(60, int(float(a.get("en_minutos", 1)) * 60))
        trigger = Trigger(object_type=TriggerType.SCHEDULED_RELATIVE, offset_in_seconds=seconds)
    request = ReminderRequest(
        request_time=now.strftime("%Y-%m-%dT%H:%M:%S"),
        trigger=trigger,
        alert_info=AlertInfo(spoken_info=SpokenInfo(content=[SpokenText(locale="es-US", text=text)])),
        push_notification=PushNotification(status=PushNotificationStatus.ENABLED),
    )
    client = handler_input.service_client_factory.get_reminder_management_service()
    client.create_reminder(reminder_request=request)


def create_timer(handler_input, a):
    seconds = max(1, int(float(a.get("segundos", 60))))
    request = TimerRequest(
        duration=f"PT{seconds}S",
        timer_label=str(a.get("etiqueta") or "Temporizador")[:40],
        creation_behavior=CreationBehavior(display_experience=DisplayExperience(visibility=Visibility.VISIBLE)),
        triggering_behavior=TriggeringBehavior(
            operation=NotifyOnlyOperation(),
            notification_config=NotificationConfig(play_audible=True),
        ),
    )
    client = handler_input.service_client_factory.get_timer_management_service()
    client.create_timer(timer_request=request)


DIAS_RRULE = {"lunes": "MO", "martes": "TU", "miercoles": "WE", "jueves": "TH", "viernes": "FR",
              "sabado": "SA", "domingo": "SU"}


def _hm(valor, defecto):
    m = re.match(r"(\d{1,2})(?:[:.](\d{2}))?", str(valor or defecto).strip()) or re.match(r"(\d{1,2}):(\d{2})", defecto)
    return min(23, int(m.group(1))), min(59, int(m.group(2) or 0))


def reglas_repeticion(rep):
    """{"frecuencia": "diaria"|"semanal"|"cada_horas", "hora", "dias", "cada_horas", "desde", "hasta"} -> RRULEs."""
    frec = _sin_tildes(str(rep.get("frecuencia") or "diaria"))
    if rep.get("cada_horas") or "hora" in frec:
        cada = max(1, int(float(rep.get("cada_horas") or 1)))
        h1, m1 = _hm(rep.get("desde"), "08:00")
        h2, _ = _hm(rep.get("hasta"), "22:00")
        return [f"FREQ=DAILY;BYHOUR={h};BYMINUTE={m1};BYSECOND=0;INTERVAL=1;" for h in range(h1, h2 + 1, cada)][:12]
    h, m = _hm(rep.get("hora"), "09:00")
    dias = rep.get("dias") or []
    if isinstance(dias, str):
        dias = re.split(r"[,\s]+", dias)
    claves = [_sin_tildes(str(d)).strip() for d in dias if str(d).strip()]
    dias = [DIAS_RRULE.get(k) or DIAS_RRULE.get(k.rstrip("s")) or k.upper()[:2] for k in claves]
    dias = [d for d in dias if d in DIAS_RRULE.values()]
    if dias or "seman" in frec:
        return [f"FREQ=WEEKLY;BYDAY={','.join(dias or ['MO'])};BYHOUR={h};BYMINUTE={m};BYSECOND=0;INTERVAL=1;"]
    return [f"FREQ=DAILY;BYHOUR={h};BYMINUTE={m};BYSECOND=0;INTERVAL=1;"]


def gestionar_recordatorios(handler_input, kind, a):
    """Lee o borra los recordatorios de Alexa creados por esta skill."""
    client = handler_input.service_client_factory.get_reminder_management_service()
    activos = [r for r in (client.get_reminders().alerts or [])
               if str(getattr(r.status, "value", r.status)).upper() == "ON"]

    def texto(r):
        try:
            return r.alert_info.spoken_info.content[0].text
        except Exception:
            return "recordatorio"

    if kind == "recordatorios":
        if not activos:
            return "No tienes recordatorios activos."
        partes = []
        for r in activos[:8]:
            tr = r.trigger
            if tr and tr.recurrence:
                cuando = "se repite"
            elif tr and tr.scheduled_time:
                st = tr.scheduled_time
                st = st if isinstance(st, datetime) else datetime.fromisoformat(str(st)[:19])
                cuando = st.strftime("el %d/%m a las %H:%M")
            else:
                cuando = ""
            partes.append(f"{texto(r)} {cuando}".strip())
        return f"Tienes {len(activos)} recordatorios: " + "; ".join(partes) + "."
    objetivo = _sin_tildes(str(a.get("texto") or "")).strip()
    if not objetivo:
        return "¿Qué recordatorio quieres borrar?"
    borrar = activos if objetivo in ("todos", "todo") else [r for r in activos if objetivo in _sin_tildes(texto(r))]
    for r in borrar:
        client.delete_reminder(alert_token=r.alert_token)
    if not borrar:
        return "No encontré ese recordatorio."
    return f"Listo, borré {len(borrar)} recordatorio{'s' if len(borrar) > 1 else ''}."


# ---------- datos en vivo, gratis y sin claves ----------

ESTADOS_CIELO = ((0, "despejado"), (1, "mayormente despejado"), (2, "parcialmente nublado"), (3, "nublado"),
                 (48, "con niebla"), (57, "con llovizna"), (67, "con lluvia"), (77, "con nieve"),
                 (82, "con chaparrones"), (86, "con nevadas"), (99, "con tormentas"))
DIAS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES_ES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
            "noviembre", "diciembre")


def _leer_web(url, timeout=2.5):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Cerebro)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def clima(ciudad="", dia=0):
    lat, lon, nombre = config.LATITUDE, config.LONGITUDE, config.CITY
    ciudad = str(ciudad or "").strip()
    if ciudad and _sin_tildes(ciudad) not in _sin_tildes(config.CITY):
        g = json.loads(_leer_web("https://geocoding-api.open-meteo.com/v1/search?count=1&language=es&name="
                                 + urllib.parse.quote(ciudad)))
        r = (g.get("results") or [None])[0]
        if not r:
            return f"No encontré la ciudad {ciudad}."
        lat, lon, nombre = r["latitude"], r["longitude"], r["name"]
    try:
        dia = max(0, min(6, int(dia or 0)))
    except (TypeError, ValueError):
        dia = 0
    d = json.loads(_leer_web(
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lat}&longitude={lon}&timezone=auto&forecast_days={dia + 1}"
        "&current=temperature_2m,weather_code"
        "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"))
    dd = d["daily"]
    estado = next((txt for tope, txt in ESTADOS_CIELO if dd["weather_code"][dia] <= tope), "variable")
    cuando = ("hoy" if dia == 0 else "mañana" if dia == 1 else
              "el " + DIAS_ES[(now_local() + timedelta(days=dia)).weekday()])
    texto = (f"En {nombre}, {cuando} va a estar {estado}, con mínima de {round(dd['temperature_2m_min'][dia])} "
             f"y máxima de {round(dd['temperature_2m_max'][dia])} grados, y {dd['precipitation_probability_max'][dia] or 0} "
             "por ciento de probabilidad de lluvia.")
    if dia == 0:
        texto = f"Ahora hace {round(d['current']['temperature_2m'])} grados. " + texto
    return texto


def dolar():
    datos = {x.get("casa"): x for x in json.loads(_leer_web("https://dolarapi.com/v1/dolares"))}
    partes = [f"{dicho}, {round(datos[casa]['venta'])}" for casa, dicho in
              (("oficial", "oficial"), ("blue", "blue"), ("bolsa", "MEP"), ("tarjeta", "tarjeta"))
              if datos.get(casa, {}).get("venta")]
    return ("El dólar a la venta: " + "; ".join(partes) + " pesos.") if partes else "No pude leer la cotización."


def noticias(tema=""):
    import xml.etree.ElementTree as ET
    base = "https://news.google.com/rss"
    url = (base + "/search?q=" + urllib.parse.quote(tema) + "&" if tema else base + "?") + "hl=es-419&gl=AR&ceid=AR:es-419"
    items = list(ET.fromstring(_leer_web(url)).iter("item"))[:5]
    titulos = [str(i.findtext("title") or "").rsplit(" - ", 1)[0].strip() for i in items]
    if not titulos:
        return "No encontré noticias" + (f" sobre {tema}." if tema else ".")
    return (f"Noticias sobre {tema}: " if tema else "Los titulares de hoy: ") + ". ".join(titulos) + "."


def info_rapida(frase):
    """Clima, dólar y noticias sin pasar por la IA."""
    t = _sin_tildes(frase).replace("ñ", "n").strip(" .!?¡¿,")
    try:
        if t in ("que hora es", "que hora son", "hora", "decime la hora", "me decis la hora", "que horas son"):
            n = now_local()
            return f"Son las {n.hour}:{n.minute:02d}."
        if t in ("que dia es hoy", "que fecha es hoy", "que dia es", "fecha", "a que estamos hoy", "que dia estamos",
                 "que fecha es"):
            n = now_local()
            return f"Hoy es {DIAS_ES[n.weekday()]} {n.day} de {MESES_ES[n.month - 1]}."
        if t in ("clima", "el clima", "que tiempo hace", "como esta el clima", "como esta el tiempo", "va a llover",
                 "va a llover hoy", "que temperatura hace", "cuantos grados hace", "el pronostico", "el clima de hoy",
                 "que clima hace", "pronostico"):
            return clima()
        if t in ("clima de manana", "el clima de manana", "que tiempo va a hacer manana", "va a llover manana",
                 "el pronostico de manana", "como va a estar el clima manana", "que clima va a hacer manana"):
            return clima(dia=1)
        conv = convertir(t)
        if conv:
            return conv
        if re.search(r"\b(proximo feriado|hay feriado|cuando es el feriado|el feriado|feriado largo|feriados)\b", t) \
                and len(t) < 60:
            return proximo_feriado()
        if "riesgo pais" in t and len(t) < 45:
            return riesgo_pais()
        if "inflacion" in t and len(t) < 45 and not t.startswith(("que es", "explicame")):
            return inflacion()
        if "dolar" in t and len(t) < 40 and not t.startswith(("no ", "cuando")) and "alerta" not in t \
                and not re.match(r"(activa|desactiva|apaga|prende|saca|pone)", t):
            return dolar()
        m = re.match(r"(como salio|cuando juega|contra quien juega|a que hora juega|resultado de|como va el partido de)"
                     r"\s+(el |la )?(.+)$", t)
        if m:
            r = futbol(m.group(3))
            return None if r.startswith("No encontré") else r
        if t in ("partidos de hoy", "los partidos", "como salieron los partidos", "resultados del futbol", "futbol",
                 "la fecha del futbol", "que partidos hay", "los partidos de hoy"):
            return futbol()
        m = re.match(r"(a cuanto esta|cuanto esta|cuanto vale|como esta|cotizacion del?|precio del?)\s+(el |la )?"
                     r"(euro|real|peso chileno|peso uruguayo|bitcoin|ethereum|cripto)$", t)
        if m:
            return cotizacion(m.group(3))
        if t in ("noticias", "las noticias", "que noticias hay", "titulares", "los titulares", "dame las noticias",
                 "contame las noticias", "cuentame las noticias", "que paso hoy", "leeme las noticias"):
            return noticias()
    except Exception as e:
        logger.warning("info rapida: %s", e)
    return None


# ---------- voz al instante: temporizadores y recordatorios sin IA ----------

NUMEROS_ES = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
              "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14, "quince": 15,
              "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
              "veinticinco": 25, "treinta": 30, "cuarenta": 40, "cuarenta y cinco": 45, "cincuenta": 50,
              "sesenta": 60, "noventa": 90}
_NUM = r"\b(\d+(?:[.,]\d+)?|" + "|".join(sorted(NUMEROS_ES, key=len, reverse=True)) + r")"
_UNIDAD = r"\s*(horas?|hs|minutos?|mins?|segundos?|segs?)\b"


def _numero(s):
    s = s.strip()
    return NUMEROS_ES[s] if s in NUMEROS_ES else float(s.replace(",", "."))


def duracion(t):
    """Segundos de 'diez minutos', '1 hora y media', 'media hora', '30 segundos'; None si no dice un tiempo."""
    total = 0.0
    if re.search(r"\bmedia hora\b", t):
        total += 1800
    if re.search(r"\bcuarto de hora\b", t):
        total += 900
    for m in re.finditer(_NUM + _UNIDAD, t):
        n, u = _numero(m.group(1)), m.group(2)
        total += n * (3600 if u.startswith("h") else 60 if u.startswith("m") else 1)
    if re.search(r"\bhoras?\s+y\s+media\b", t):
        total += 1800
    return int(total) or None


def decir_duracion(seg):
    h, resto = divmod(int(seg), 3600)
    m, s = divmod(resto, 60)
    partes = []
    if h:
        partes.append("una hora" if h == 1 else f"{h} horas")
    if m:
        partes.append("un minuto" if m == 1 else f"{m} minutos")
    if s:
        partes.append(f"{s} segundos")
    return " y ".join(partes) or "un momento"


def gestionar_temporizadores(handler_input, kind):
    client = handler_input.service_client_factory.get_timer_management_service()
    activos = [x for x in (client.get_timers().timers or [])
               if str(getattr(x.status, "value", x.status)).upper() in ("ON", "PAUSED")]
    if not activos:
        return "No tienes temporizadores activos."
    if kind == "cancelar_temporizador":
        client.delete_timers()
        return "Listo, cancelé " + ("el temporizador." if len(activos) == 1 else f"los {len(activos)} temporizadores.")
    partes = []
    for x in activos[:3]:
        nombre = f"de {x.timer_label}" if x.timer_label and x.timer_label != "Temporizador" else ""
        if str(getattr(x.status, "value", x.status)).upper() == "PAUSED":
            partes.append(f"el temporizador {nombre} está en pausa".replace("  ", " "))
            continue
        tt = x.trigger_time
        tt = tt if isinstance(tt, datetime) else datetime.fromisoformat(str(tt).replace("Z", "+00:00"))
        if tt.tzinfo is None:
            tt = tt.replace(tzinfo=timezone.utc)
        falta = max(0, (tt - datetime.now(timezone.utc)).total_seconds())
        partes.append(f"al temporizador {nombre} le faltan {decir_duracion(falta)}".replace("  ", " "))
    texto = "; ".join(partes)
    return texto[0].upper() + texto[1:] + "."


NUMEROS_HORA = {"una": 1, "un": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "ocho": 8, "doce": 12}


def _cada_horas(orig):
    """'recordame tomar agua cada 2 horas' / 'recordame cada dos horas tomar agua' -> ('tomar agua', 2)."""
    o = orig.lower().strip(" .!?¡¿,")
    if re.search(r"\b(celular|telegram|telefono|teléfono|desde|hasta)\b", o):
        return None                      # al celular o con horario propio: lo piensa la IA
    verbo = r"(?:recordame|recordarme|recuerdame|recuérdame|acordame)\s+"
    numero = r"(?P<n>\d{1,2}|una|un|dos|tres|cuatro|cinco|seis|ocho|doce)?\s*"
    for patron in (verbo + r"(?:de\s+)?(?P<texto>.+?)\s+cada\s+" + numero + r"horas?$",
                   verbo + r"cada\s+" + numero + r"horas?\s+(?:de\s+)?(?P<texto>.+)$"):
        m = re.match(patron, o)
        if m and m.group("texto").strip(" ,.") and not re.match(r"(que|me|te) ", m.group("texto")):
            n = m.group("n") or "1"
            horas = int(n) if n.isdigit() else NUMEROS_HORA.get(n, 0)
            if 1 <= horas <= 12:
                return m.group("texto").strip(" ,."), horas
    return None


def voz_rapida(handler_input, query):
    """Temporizadores y recordatorios sin pasar por la IA. Devuelve (texto, permisos) o None."""
    orig = query.lower().strip(" .!?¡¿,")
    t = _sin_tildes(orig).replace("ñ", "n")
    if t.startswith(("no ", "no,", "cuando ")):
        return None
    es_timer = re.search(r"\b(temporizador|temporizadores|timer|cronometro)\b", t)
    kind = None
    if es_timer and (t.startswith("para ") or re.search(
            r"\b(cancel|borr|elimin|fren|apag|saca|quita|detene)\w*", t)):
        kind = "cancelar_temporizador"
    elif es_timer and re.search(r"\bcuanto\b.*\b(falta|queda)", t):
        kind = "temporizadores"
    try:
        if kind:
            if not has_permission(handler_input, TIMERS_SCOPE):
                return "Para usar temporizadores necesito tu permiso. Te dejé una tarjeta en la app de Alexa.", [TIMERS_SCOPE]
            return gestionar_temporizadores(handler_input, kind), []
        if es_timer or re.match(r"(avisame|llamame) en ", t):
            seg = duracion(t)
            if not seg or "cada" in t or "a las" in t:
                return None
            m = re.search(r"\bpara\s+(el |la |los |las )?(.+)$", t)
            etiqueta = orig[m.start(2):].strip() if m and not duracion(m.group(2)) else ""
            if not has_permission(handler_input, TIMERS_SCOPE):
                return "Para usar temporizadores necesito tu permiso. Te dejé una tarjeta en la app de Alexa.", [TIMERS_SCOPE]
            create_timer(handler_input, {"segundos": seg, "etiqueta": etiqueta or "Temporizador"})
            return f"Listo, temporizador de {decir_duracion(seg)}" + (f" para {etiqueta}" if etiqueta else "") + ".", []
        if re.match(r"(que|cuales) (recordatorios|alarmas) tengo|(mis|los) (recordatorios|alarmas)$|tengo (algun |"
                    r"alguna )?(recordatorio|alarma)s?( puestos?| puestas?)?$", t):
            if not has_permission(handler_input, REMINDERS_SCOPE):
                return ("Para ver tus recordatorios necesito tu permiso. Te dejé una tarjeta en la app de Alexa.",
                        [REMINDERS_SCOPE])
            return gestionar_recordatorios(handler_input, "recordatorios", {}), []
        repetido = _cada_horas(orig)
        if repetido:
            texto, horas = repetido
            if not has_permission(handler_input, REMINDERS_SCOPE):
                return ("Para crear recordatorios necesito tu permiso. Te dejé una tarjeta en la app de Alexa.",
                        [REMINDERS_SCOPE])
            repetir = {"frecuencia": "cada_horas", "cada_horas": horas, "desde": "08:00", "hasta": "22:00"}
            cada = "cada hora" if horas == 1 else f"cada {horas} horas"
            try:
                create_reminder(handler_input, {"texto": texto, "repetir": repetir})
            except Exception as e:           # Alexa no lo aceptó: que lo avise la PC por Telegram
                logger.warning("recordatorio repetido: %s", e)
                tipo, dicho = run_pc_action({"accion": "programar", "datos": {**repetir, "texto": texto, "tipo": "aviso"}},
                                            time.time() + 4.0)
                return (dicho if tipo == "problem" else "Alexa no me dejó repetirlo en el Echo. " +
                        (dicho or "Te aviso al celular.")), []
            return f"Listo, te recuerdo {texto} {cada}, de 8 de la mañana a 10 de la noche.", []
        alarma = alarma_rapida(handler_input, orig, t)
        if alarma:
            return alarma
        m = re.match(r"(recordame|recordarme|acordame|recorda)\s+(que\s+)?(.+)$", t)
        if m and " en " in t and not re.search(
                r"\b(cada|todos|todas|a las|manana|lunes|martes|miercoles|jueves|viernes|sabado|domingo)\b", t):
            seg = duracion(m.group(3))
            q = re.search(r"\s*\ben\s+(?:\S+\s+){0,3}?(horas?|hs|minutos?|mins?|segundos?|segs?|media hora|"
                          r"cuarto de hora)\b(\s+y\s+media)?", m.group(3))
            if seg and q:
                resto = orig[m.start(3):]
                texto = (resto[:q.start()] + resto[q.end():]).strip(" ,.")
                if texto:
                    if not has_permission(handler_input, REMINDERS_SCOPE):
                        return ("Para crear recordatorios necesito tu permiso. Te dejé una tarjeta en la app de Alexa.",
                                [REMINDERS_SCOPE])
                    create_reminder(handler_input, {"texto": texto, "en_minutos": seg / 60})
                    return f"Listo, en {decir_duracion(seg)} te recuerdo {texto}.", []
    except Exception as e:
        logger.exception("voz rapida: %s", e)
        return None
    return None


# ---------- radio en vivo en el Echo ----------

def soporta_audio(handler_input):
    try:
        return handler_input.request_envelope.context.system.device.supported_interfaces.audio_player is not None
    except Exception:
        return False


def buscar_radio(nombre):
    """Busca la radio en radio-browser.info (gratis) y devuelve (nombre, url https) o None."""
    nombre = re.sub(r"^((la|el)\s+|radio\s+)+", "", str(nombre or "").strip(), flags=re.I)
    if not nombre:
        return None
    base = ("https://de1.api.radio-browser.info/json/stations/search?limit=12&hidebroken=true"
            "&order=clickcount&reverse=true&name=" + urllib.parse.quote(nombre))
    estaciones = []
    for pais in ("&countrycode=AR", ""):
        try:
            estaciones = json.loads(_leer_web(base + pais, timeout=2.0))
        except Exception as e:
            logger.warning("radio-browser: %s", e)
        if estaciones:
            break
    for e in estaciones[:6]:
        url = str(e.get("url_resolved") or e.get("url") or "")
        if not url.startswith("https://"):
            continue
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=2.0) as r:
                final, tipo = r.geturl(), str(r.headers.get("Content-Type") or "")
            if final.startswith("https://") and any(x in tipo for x in ("audio", "mpegurl", "octet")):
                corto = re.split(r"\s+-\s+|\.\s|\(|\|", str(e.get("name") or nombre))[0].strip()
                return corto or nombre, final        # "La 100 - 99.9 FM - Grupo..." -> "La 100"
        except Exception:
            continue
    return None


def _directiva_radio(radio):
    nombre, url = radio
    return PlayDirective(play_behavior=PlayBehavior.REPLACE_ALL, audio_item=AudioItem(
        stream=Stream(token=uuid.uuid4().hex, url=url, offset_in_milliseconds=0),
        metadata=AudioItemMetadata(title=nombre, subtitle="Cerebro")))


def reproducir(handler_input, texto, radio, memory=None):
    if memory is None:
        memory = load_memory(handler_input)
        memory["radio"] = list(radio)
        save_memory(handler_input, memory)
    rb = handler_input.response_builder.speak(say(texto or f"Pongo {radio[0]}."))
    rb.add_directive(_directiva_radio(radio))
    return rb.set_should_end_session(True).response


# ---------- fútbol y cotizaciones (gratis, sin claves) ----------

LIGAS = (("arg.1", "Liga Profesional"), ("conmebol.libertadores", "Libertadores"),
         ("conmebol.sudamericana", "Sudamericana"))


def _espn(liga):
    try:
        req = urllib.request.Request(
            f"https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=2.5) as r:
            return json.load(r).get("events", [])
    except Exception as e:
        logger.warning("espn %s: %s", liga, e)
        return []


def _partido(e):
    comp = e["competitions"][0]
    lados = {c.get("homeAway"): c for c in comp["competitors"]}
    local = lados.get("home") or comp["competitors"][0]
    visita = lados.get("away") or comp["competitors"][-1]
    nl, nv = local["team"]["shortDisplayName"].strip(), visita["team"]["shortDisplayName"].strip()
    estado = e["status"]["type"]["state"]
    if estado == "pre":
        cuando = datetime.fromisoformat(e["date"].replace("Z", "+00:00")).astimezone(
            timezone(timedelta(hours=config.UTC_OFFSET_HOURS)))
        hoy = now_local().date()
        dia = ("hoy" if cuando.date() == hoy else "mañana" if cuando.date() == hoy + timedelta(days=1)
               else "el " + DIAS_ES[cuando.weekday()])
        return f"{nl} contra {nv}, {dia} a las {cuando.hour}:{cuando.minute:02d}"
    marcador = f"{nl} {local.get('score', 0)}, {nv} {visita.get('score', 0)}"
    return marcador + (", en juego" if estado == "in" else ", final")


EQUIPOS_AR = {"boca": "Boca Juniors", "river": "River Plate", "racing": "Racing Club", "independiente": "Independiente",
              "san lorenzo": "San Lorenzo", "estudiantes": "Estudiantes", "velez": "Velez Sarsfield",
              "newells": "Newell's Old Boys", "rosario central": "Rosario Central", "talleres": "Talleres",
              "belgrano": "Belgrano", "lanus": "Lanus", "huracan": "Huracan", "argentinos": "Argentinos Juniors",
              "banfield": "Banfield", "gimnasia": "Gimnasia La Plata", "tigre": "Tigre", "platense": "Platense",
              "godoy cruz": "Godoy Cruz", "union": "Union Santa Fe", "colon": "Colon", "defensa": "Defensa y Justicia",
              "instituto": "Instituto", "sarmiento": "Sarmiento", "barracas": "Barracas Central",
              "seleccion": "Argentina", "argentina": "Argentina"}


def _sportsdb(ruta):
    return json.loads(_leer_web("https://www.thesportsdb.com/api/v1/json/3/" + ruta, timeout=2.5))


def _evento_sdb(e):
    local, visita = e.get("strHomeTeam"), e.get("strAwayTeam")
    if e.get("intHomeScore") not in (None, ""):
        return f"{local} {e['intHomeScore']}, {visita} {e['intAwayScore']}"
    ts = e.get("strTimestamp") or f"{e.get('dateEvent')}T{e.get('strTime') or '00:00:00'}"
    cuando = datetime.fromisoformat(str(ts)[:19]).replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=config.UTC_OFFSET_HOURS)))
    hoy = now_local().date()
    dia = ("hoy" if cuando.date() == hoy else "mañana" if cuando.date() == hoy + timedelta(days=1)
           else f"el {DIAS_ES[cuando.weekday()]} {cuando.day}")
    return f"{local} contra {visita}, {dia} a las {cuando.hour}:{cuando.minute:02d}"


def futbol_equipo(equipo):
    """Último y próximo partido de un equipo, en cualquier torneo."""
    clave = _sin_tildes(str(equipo or "")).replace("ñ", "n").strip()
    nombre = next((v for k, v in sorted(EQUIPOS_AR.items(), key=lambda x: -len(x[0]))
                   if re.search(r"\b" + k + r"\b", clave)), equipo)
    equipos = [x for x in (_sportsdb("searchteams.php?t=" + urllib.parse.quote(nombre)).get("teams") or [])
               if x.get("strSport") == "Soccer"]
    eq = next((x for x in equipos if x.get("strCountry") == "Argentina"), equipos[0] if equipos else None)
    if not eq:
        return None
    def seguro(ruta):
        try:
            return _sportsdb(ruta)
        except Exception as e:
            logger.warning("thesportsdb %s: %s", ruta, e)
            return {}

    id_eq = str(eq["idTeam"])
    ligas = [str(eq[k]) for k in ["idLeague"] + [f"idLeague{i}" for i in range(2, 8)] if eq.get(k)]
    rutas = ["eventslast.php?id=" + id_eq, "eventsnext.php?id=" + id_eq] + ["eventspastleague.php?id=" + x for x in ligas]
    with ThreadPoolExecutor(max_workers=len(rutas)) as pool:
        datos = list(pool.map(seguro, rutas))
    # la versión gratis de "últimos" solo trae partidos de local: sumamos el último de cada torneo del equipo
    pasados = (datos[0].get("results") or []) + [
        e for d in datos[2:] for e in (d.get("events") or []) if id_eq in (str(e.get("idHomeTeam")), str(e.get("idAwayTeam")))]
    pasados = [e for e in pasados if e.get("intHomeScore") not in (None, "")]
    ult = max(pasados, key=lambda e: str(e.get("strTimestamp") or e.get("dateEvent") or ""), default=None)
    prox = (datos[1].get("events") or [None])[0]
    torneos = {"Argentinian Primera Division": "por la Liga Profesional", "Copa Argentina": "por la Copa Argentina",
               "FIFA World Cup": "por el Mundial", "International Friendlies": "amistoso",
               "CONMEBOL Libertadores": "por la Libertadores", "Copa Libertadores": "por la Libertadores",
               "CONMEBOL Sudamericana": "por la Sudamericana", "Copa Sudamericana": "por la Sudamericana",
               "FIFA World Cup Qualifying CONMEBOL": "por las Eliminatorias", "Copa America": "por la Copa América"}
    partes = []
    if ult:
        partes.append(f"El último partido, {torneos.get(ult.get('strLeague'), 'por ' + str(ult.get('strLeague')))}: "
                      f"{_evento_sdb(ult)}")
    if prox:
        partes.append(f"El próximo, {torneos.get(prox.get('strLeague'), 'por ' + str(prox.get('strLeague')))}: "
                      f"{_evento_sdb(prox)}")
    return ". ".join(partes) + "." if partes else None


def futbol(equipo=""):
    objetivo = _sin_tildes(str(equipo or "")).strip()
    if objetivo:
        try:
            r = futbol_equipo(equipo)
            if r:
                return r
        except Exception as e:
            logger.warning("thesportsdb: %s", e)
    with ThreadPoolExecutor(max_workers=len(LIGAS)) as pool:
        resultados = list(zip(LIGAS, pool.map(_espn, [codigo for codigo, _ in LIGAS])))
    if not objetivo:
        eventos = resultados[0][1]
        if not eventos:
            return "No encontré partidos de la liga en esta fecha."
        return "Partidos de la fecha: " + "; ".join(_partido(e) for e in eventos[:8]) + "."
    for (_, liga), eventos in resultados:
        for e in eventos:
            nombres = " ".join(c["team"].get("displayName", "") + " " + c["team"].get("shortDisplayName", "")
                               for c in e["competitions"][0]["competitors"])
            if objetivo in _sin_tildes(nombres):
                return f"{liga}: {_partido(e)}."
    return f"No encontré un partido de {equipo} en esta fecha."


def cotizacion(moneda=""):
    m = _sin_tildes(str(moneda or ""))
    if any(x in m for x in ("bitcoin", "btc", "ethereum", "ether", "cripto")):
        cual = "ethereum" if "ether" in m else "bitcoin"
        d = json.loads(_leer_web("https://api.coingecko.com/api/v3/simple/price?ids=" + cual + "&vs_currencies=usd"))
        return f"El {cual} está a {round(d[cual]['usd'])} dólares."
    codigos = (("euro", "EUR", "El euro"), ("real", "BRL", "El real"), ("chileno", "CLP", "El peso chileno"),
               ("uruguayo", "UYU", "El peso uruguayo"), ("dolar", "USD", "El dólar"))
    cod, dicho = next(((c, d) for k, c, d in codigos if k in m), ("EUR", "El euro"))
    datos = {x.get("moneda"): x for x in json.loads(_leer_web("https://dolarapi.com/v1/cotizaciones"))}
    x = datos.get(cod)
    if not x or not x.get("venta"):
        return "No encontré esa moneda."
    valor = float(x["venta"])
    numero = str(round(valor)) if valor >= 100 else f"{valor:.2f}".replace(".", ",")
    return f"{dicho} oficial está a {numero} pesos a la venta."


# ---------- alarmas y recordatorios con hora, sin IA ----------

HORAS_ES = {k: v for k, v in NUMEROS_ES.items() if v <= 24 and " " not in k}
DIAS_PLANOS = ("lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo")


def cuando_absoluto(t, temprano=False):
    """'a las 7', 'mañana a las 18:30', 'el lunes a las 9 de la noche' -> (datetime local, tramos a quitar)."""
    m = re.search(r"\ba\s+las?\s+(\d{1,2}|" + "|".join(sorted(HORAS_ES, key=len, reverse=True)) + r")"
                  r"(?:(?::|\.|\s+y\s+)(\d{2}|media|cuarto|quince|treinta|cuarenta y cinco))?"
                  r"(?:\s*(?:hs|horas|en punto))?(?:\s+de\s+la\s+(manana|tarde|noche|madrugada))?", t)
    if not m:
        return None
    h = int(m.group(1)) if m.group(1).isdigit() else HORAS_ES[m.group(1)]
    mi = 0
    if m.group(2):
        mi = {"media": 30, "cuarto": 15, "quince": 15, "treinta": 30, "cuarenta y cinco": 45}.get(m.group(2))
        mi = mi if mi is not None else min(59, int(m.group(2)))
    parte = m.group(3)
    if parte in ("tarde", "noche") and h < 12:
        h += 12
    if h > 23:
        return None
    ahora = now_local().replace(tzinfo=None, second=0, microsecond=0)
    tramos = [m.span()]
    dia, explicito = ahora.date(), False
    md = re.search(r"(?<!de la )\b(pasado manana|manana)\b", t)
    mw = re.search(r"\b(el\s+)?(" + "|".join(DIAS_PLANOS) + r")\b", t)
    if md:
        dia, explicito = ahora.date() + timedelta(days=2 if md.group(1) == "pasado manana" else 1), True
        tramos.append(md.span())
    elif mw:
        delta = (DIAS_PLANOS.index(mw.group(2)) - ahora.weekday()) % 7 or 7
        dia, explicito = ahora.date() + timedelta(days=delta), True
        tramos.append(mw.span())
    horas = [h] if (parte or h >= 12 or temprano) else [h, h + 12]
    for hh in horas:
        c = datetime(dia.year, dia.month, dia.day, hh, mi)
        if c > ahora:
            return c, tramos
    if not explicito:
        siguiente = dia + timedelta(days=1)
        return datetime(siguiente.year, siguiente.month, siguiente.day, horas[0], mi), tramos
    return None


def decir_cuando(c):
    hoy = now_local().date()
    dia = ("hoy" if c.date() == hoy else "mañana" if c.date() == hoy + timedelta(days=1)
           else f"el {DIAS_ES[c.weekday()]} {c.day}")
    return f"{dia} a las {c.hour}:{c.minute:02d}"


def alarma_rapida(handler_input, orig, t):
    """'despertame a las 7', 'recordame mañana a las 9 llamar al contador'. Devuelve (texto, permisos) o None."""
    alarma = re.match(r"(despertame|levantame|poneme (una |la )?alarma|pone (una |la )?alarma|alarma)\b", t)
    pedido = re.match(r"(recordame|recordarme|acordame|recorda|avisame)\s+(que\s+)?", t)
    if not (alarma or pedido) or not re.search(r"\ba\s+las?\s", t) or re.search(r"\b(cada|todos|todas)\b", t):
        return None
    r = cuando_absoluto(t, temprano=bool(alarma))
    if not r:
        return None
    cuando, tramos = r
    if alarma:
        texto = "Es hora de levantarse" if re.match(r"(desperta|levanta)", t) else "Alarma"
    else:
        quitar = sorted(tramos + [pedido.span()])
        partes, pos = [], 0
        for a, b in quitar:
            partes.append(orig[pos:a])
            pos = max(pos, b)
        partes.append(orig[pos:])
        texto = re.sub(r"\s+", " ", " ".join(partes)).strip(" ,.")
        con_que = bool(pedido.group(2)) or texto.startswith("que ")
        texto = re.sub(r"^(que|de|a)\s+", "", texto).strip()
        if not texto:
            return None
    if not has_permission(handler_input, REMINDERS_SCOPE):
        return ("Para crear recordatorios necesito tu permiso. Te dejé una tarjeta en la app de Alexa.",
                [REMINDERS_SCOPE])
    create_reminder(handler_input, {"texto": texto, "fecha_hora": cuando.strftime("%Y-%m-%dT%H:%M:%S")})
    if alarma:
        return f"Listo, {decir_cuando(cuando)} te despierto.", []
    return f"Listo, {decir_cuando(cuando)} te recuerdo {'que ' if con_que else ''}{texto}.", []


# ---------- Argentina: feriados, riesgo país, inflación y conversiones ----------

PALABRAS_NUM = {"cien": 100, "ciento": 100, "doscientos": 200, "trescientos": 300, "cuatrocientos": 400,
                "quinientos": 500, "seiscientos": 600, "setecientos": 700, "ochocientos": 800, "novecientos": 900,
                "mil": 1000, "millon": 1000000, "millones": 1000000, "veintiuno": 21, "veintidos": 22,
                "veintitres": 23, "treintaicinco": 35}
PALABRAS_NUM.update({k: v for k, v in NUMEROS_ES.items() if " " not in k})


def numero_es(s):
    """'100', '100.000', 'cien', 'dos mil quinientos' -> número, o None."""
    s = s.strip()
    plano = s.replace(".", "").replace(",", ".")
    if re.fullmatch(r"\d+(\.\d+)?", plano):
        return float(plano)
    total = parcial = 0
    for w in s.split():
        if w == "y":
            continue
        v = PALABRAS_NUM.get(w)
        if v is None:
            return None
        if v >= 1000:
            total += (parcial or 1) * v
            parcial = 0
        else:
            parcial += v
    return float(total + parcial) or None


def _ar(ruta):
    return json.loads(_leer_web("https://api.argentinadatos.com/v1/" + ruta))


def proximo_feriado():
    hoy = now_local().date()
    feriados = []
    for anio in (hoy.year, hoy.year + 1):
        try:
            feriados += [f for f in _ar(f"feriados/{anio}") if datetime.fromisoformat(f["fecha"]).date() >= hoy]
        except Exception as e:
            logger.warning("feriados %s: %s", anio, e)
        if feriados:
            break
    if not feriados:
        return "No encontré el próximo feriado."
    f = min(feriados, key=lambda x: x["fecha"])
    d = datetime.fromisoformat(f["fecha"]).date()
    faltan = (d - hoy).days
    cuando = ("hoy" if faltan == 0 else "mañana" if faltan == 1
              else f"el {DIAS_ES[d.weekday()]} {d.day} de {MESES_ES[d.month - 1]}, en {faltan} días")
    extra = " Es un día no laborable, no un feriado." if f.get("tipo") == "puente" else ""
    return f"El próximo feriado es {cuando}: {f['nombre']}.{extra}"


def riesgo_pais():
    d = _ar("finanzas/indices/riesgo-pais/ultimo")
    return f"El riesgo país está en {round(d['valor'])} puntos."


def inflacion():
    lista = _ar("finanzas/indices/inflacion")
    u, a = lista[-1], lista[-2]
    mes, mes_ant = MESES_ES[int(u["fecha"][5:7]) - 1], MESES_ES[int(a["fecha"][5:7]) - 1]
    v = lambda x: str(x).replace(".", ",")
    return f"La inflación de {mes} fue de {v(u['valor'])} por ciento. En {mes_ant} había sido {v(a['valor'])}."


def _dolar_blue():
    d = json.loads(_leer_web("https://dolarapi.com/v1/dolares/blue"))
    return f"El dólar blue está a {round(d['venta'])}."


def _plata(x):
    return str(round(x)) if x >= 100 or float(x).is_integer() else f"{x:.2f}".replace(".", ",")


def convertir(t):
    """'cuántos pesos son 100 dólares', 'pasame 50 euros a pesos', 'cuántos dólares son 100000 pesos'."""
    monedas = r"(dolares?|euros?|reales?)"
    a_pesos = (re.match(r"cuant[oa]s?\s+(?:pesos\s+)?(?:son|es|serian|vienen a ser)\s+(.+?)\s+" + monedas +
                        r"(?:\s+(?:en|a)\s+pesos)?$", t)
               or re.match(r"(?:pasame|converti|pasa|cambiame)\s+(.+?)\s+" + monedas + r"\s+(?:a|en)\s+pesos$", t))
    a_moneda = (re.match(r"cuant[oa]s?\s+" + monedas + r"\s+(?:son|es|serian)\s+(.+?)\s+pesos$", t)
                or re.match(r"(?:pasame|converti|pasa|cambiame)\s+(.+?)\s+pesos\s+(?:a|en)\s+" + monedas + r"$", t))
    if not (a_pesos or a_moneda):
        return None
    if a_pesos:
        monto, moneda = numero_es(a_pesos.group(1)), a_pesos.group(2)
    elif a_moneda.re.pattern.startswith("cuant"):
        moneda, monto = a_moneda.group(1), numero_es(a_moneda.group(2))
    else:
        monto, moneda = numero_es(a_moneda.group(1)), a_moneda.group(2)
    if not monto:
        return None
    if moneda.startswith("dolar"):
        dol = {x.get("casa"): x for x in json.loads(_leer_web("https://dolarapi.com/v1/dolares"))}
        blue, oficial = float(dol["blue"]["venta"]), float(dol["oficial"]["venta"])
        if a_pesos:
            return (f"{_plata(monto)} dólares son {_plata(monto * blue)} pesos al blue "
                    f"y {_plata(monto * oficial)} al oficial.")
        return (f"{_plata(monto)} pesos son {_plata(monto / blue)} dólares al blue "
                f"y {_plata(monto / oficial)} al oficial.")
    cod, nombre = ("EUR", "euros") if moneda.startswith("euro") else ("BRL", "reales")
    tasa = float({x.get("moneda"): x for x in json.loads(_leer_web("https://dolarapi.com/v1/cotizaciones"))}[cod]["venta"])
    if a_pesos:
        return f"{_plata(monto)} {nombre} son {_plata(monto * tasa)} pesos al oficial."
    return f"{_plata(monto)} pesos son {_plata(monto / tasa)} {nombre} al oficial."


# ---------- que nunca se quede callada ----------

def aviso_progresivo(handler_input, texto="Un segundo."):
    """Si algo tarda, Alexa dice 'Un segundo' mientras seguimos trabajando (no suma demora)."""
    try:
        pedido = SendDirectiveRequest(
            header=Header(request_id=handler_input.request_envelope.request.request_id),
            directive=SpeakDirective(speech=f"<speak>{escape(texto)}</speak>"))
        handler_input.service_client_factory.get_directive_service().enqueue(pedido)
    except Exception as e:
        logger.info("aviso progresivo: %s", e)


def contestar(handler_input, pregunta, texto, **kw):
    """Responde y anota el turno en la charla, así entiende lo que sigue ('¿y mañana?', 'repetí')."""
    session = handler_input.attributes_manager.session_attributes
    historia = session.get("history", []) + [{"role": "user", "content": pregunta},
                                             {"role": "assistant", "content": texto}]
    session["history"] = historia[-MAX_SESSION_HISTORY:]
    session["ultima"] = texto
    return respond(handler_input, texto, **kw)


def es_atajo(frase, atajos):
    """¿Es una de las frases que el usuario le enseñó a la PC? Tolera errores de la voz ("modo sine")."""
    import difflib
    t = _sin_tildes(frase).replace("ñ", "n").strip(" .!?¡¿,")
    for a in atajos or []:
        a = _sin_tildes(str(a)).replace("ñ", "n").strip()
        if not a:
            continue
        if t == a or difflib.SequenceMatcher(None, a, t).ratio() >= 0.85:
            return True
        if len(a) >= 5 and len(t) <= len(a) + 20 and re.search(r"(^|\s)" + re.escape(a) + r"($|\s)", t):
            return True
    return False


def _dice_lo_mismo(a, b):
    """¿Casi todas las palabras de a ya están en b? ('Desactivé las alertas.' vs 'Listo, desactivé las alertas.')"""
    pa = set(re.findall(r"\w{3,}", _sin_tildes(a)))
    pb = set(re.findall(r"\w{3,}", _sin_tildes(b)))
    return bool(pa) and len(pa & pb) / len(pa) >= 0.6


def compose_answer(speech, out):
    if out["confirm"]:
        return out["confirm"]
    if out["problems"]:
        return " ".join(out["problems"] + out["info"])
    if out["info"] and len(speech) <= 25:   # "Un momento." sobra cuando ya tenemos el resultado
        speech = ""
    elif out["info"] and _dice_lo_mismo(speech, " ".join(out["info"])):
        speech = ""                          # la PC ya lo confirma: no repetirlo dos veces
    return " ".join(x for x in [speech] + out["info"] if x) or "Listo."


# ---------- memory ----------

def load_memory(handler_input):
    try:
        attrs = handler_input.attributes_manager.persistent_attributes or {}
    except Exception as e:
        logger.exception("load memory failed: %s", e)
        attrs = {}
    attrs.setdefault("facts", [])
    attrs.setdefault("recent", [])
    return attrs


def save_memory(handler_input, memory):
    try:
        handler_input.attributes_manager.persistent_attributes = memory
        handler_input.attributes_manager.save_persistent_attributes()
    except Exception as e:
        logger.exception("save memory failed: %s", e)


def respond(handler_input, text, end=False, permissions=None):
    rb = handler_input.response_builder.speak(say(text))
    if permissions:
        rb.set_card(AskForPermissionsConsentCard(permissions=list(dict.fromkeys(permissions))))
    if not end:
        rb.ask(say("Te escucho."))
    return rb.set_should_end_session(end).response


# ---------- handlers ----------

class LaunchHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        return respond(handler_input, "Hola. ¿En qué te ayudo?")


class ChatHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("ChatIntent")(handler_input)

    def handle(self, handler_input):
        # Si algo tarda más de lo normal, Alexa dice "Un segundo" en vez de quedarse callada.
        alerta = threading.Timer(1.8, aviso_progresivo, args=(handler_input,))
        alerta.daemon = True
        alerta.start()
        try:
            return self._handle(handler_input)
        finally:
            alerta.cancel()

    def _handle(self, handler_input):
        deadline = time.time() + ALEXA_BUDGET
        slots = handler_input.request_envelope.request.intent.slots or {}
        query = (slots.get("query").value if slots.get("query") else None) or ""
        if not query:
            return respond(handler_input, "No te entendí. ¿Puedes repetirlo?")

        session = handler_input.attributes_manager.session_attributes
        normalized = query.lower().strip(" .!?¡¿,")

        pending = session.pop("pending", None)
        if pending and normalized in YES:
            pending["_confirmado"] = True
            memory = load_memory(handler_input)
            out = run_actions(handler_input, [pending], memory, deadline)
            return respond(handler_input, compose_answer("Listo.", out))
        if pending and normalized in NO:
            return respond(handler_input, "Cancelado.")

        if normalized in CALLS:
            return respond(handler_input, random.choice(ACKS))
        if normalized in GOODBYES:
            return respond(handler_input, "Hasta luego.", end=True)
        if _sin_tildes(normalized) in ("repeti", "repetilo", "repetimelo", "repetime", "que dijiste", "como",
                                       "no te escuche", "de nuevo lo que dijiste", "perdon que dijiste"):
            return respond(handler_input, session.get("ultima") or "Todavía no te dije nada.")

        rapido = voz_rapida(handler_input, query)
        if rapido:                       # temporizadores y recordatorios: al instante, sin IA
            return contestar(handler_input, query, rapido[0], permissions=rapido[1])
        m = re.match(r"(pone|poneme|pasame|quiero escuchar|escuchar|reproduci)\s+(la\s+)?radio\s+(.+)$",
                     _sin_tildes(query).strip(" .!?¡¿,"))
        if m:                            # "poné la radio Mitre": suena en el Echo
            radio = buscar_radio(m.group(3)) if soporta_audio(handler_input) else None
            if radio:
                return reproducir(handler_input, None, radio)
            return contestar(handler_input, query, "No encontré esa radio para reproducir acá.")

        vivo = info_rapida(query)
        if vivo:                         # clima, dólar, noticias: directo, sin IA
            return contestar(handler_input, query, vivo)

        partes = [x for x in re.split(r"\s+y\s+(?:despu[eé]s\s+|luego\s+)?|\s*,\s*", query) if x.strip()]
        if len(partes) > 1:
            ordenes = [via_rapida(x) for x in partes]
            if all(ordenes):             # todas son órdenes conocidas: sin IA, una atrás de otra
                for accion, datos, _ in ordenes:
                    tipo, texto = run_pc_action({"accion": accion, "datos": datos}, deadline)
                    if tipo == "problem":
                        return contestar(handler_input, query, texto)
                return contestar(handler_input, query, "Listo.")

        rapida = via_rapida(query)
        if rapida:                       # comando de siempre: directo a la PC, sin IA
            accion, datos, dicho = rapida
            tipo, texto = run_pc_action({"accion": accion, "datos": datos}, deadline)
            if tipo == "problem":
                return contestar(handler_input, query, texto)
            return contestar(handler_input, query, texto or dicho or "Listo.")

        memory = load_memory(handler_input)
        history = session.get("history", [])
        history.append({"role": "user", "content": query})

        sync = ThreadPoolExecutor(max_workers=1)   # mientras piensa la IA, traemos las frases aprendidas
        frases_pc = sync.submit(send_to_pc, "aprendidos", {}, 3.0) if pc_link()[0] else None
        raw = None
        respaldo = None
        for intento in range(2):         # si Google rechaza por exceso de pedidos, un reintento enseguida
            try:
                espera = min(config.AI_TIMEOUT, deadline - time.time() - 1.0)
                if espera < 1.5:
                    break
                raw = ask_ai(build_system_prompt(memory["facts"], memory["recent"]), history[-MAX_SESSION_HISTORY:],
                             timeout=espera)
                dicho, hechas = split_actions(raw)
                if intento == 0 and not hechas and _sin_tildes(dicho).strip(" .!¡,") in (
                        "un momento", "un segundo", "listo", "ok", "hecho", "dale", "enseguida"):
                    respaldo, raw = raw, None      # dijo que lo hacía pero no hizo nada: otra vez
                    continue
                break
            except Exception as e:
                logger.warning("ai failed (intento %s): %s", intento + 1, e)
                time.sleep(0.4)
        raw = raw or respaldo
        if raw is None:
            history.pop()                # que el pedido fallido no se mezcle con el próximo
            session["history"] = history[-MAX_SESSION_HISTORY:]
            sync.shutdown(wait=False)
            return respond(handler_input, "Se me cortó la conexión con la inteligencia. ¿Me lo repetís?")

        speech, actions = split_actions(raw)
        try:
            r = frases_pc.result(timeout=0.3) if frases_pc else None
            if r and r.get("ok"):         # lo que aprendió (lecciones) también lo tiene en cuenta la voz
                lecciones = [x for x in json.loads(r.get("texto") or "[]")
                             if str(x).startswith("Cuando el usuario dice")][-20:]
                memory["facts"] = ([f for f in memory["facts"] if not f.startswith("Cuando el usuario dice")]
                                   + lecciones)[-MAX_FACTS:]
                memory["atajos"] = []
        except Exception:
            pass
        finally:
            sync.shutdown(wait=False)
        out = run_actions(handler_input, actions, memory, deadline)
        answer = compose_answer(speech, out)

        history.append({"role": "assistant", "content": answer})
        session["ultima"] = answer
        session["history"] = history[-MAX_SESSION_HISTORY:]
        memory["recent"] = (memory["recent"] + history[-2:])[-MAX_RECENT:]
        save_memory(handler_input, memory)
        if out.get("audio") and not out["problems"]:
            return reproducir(handler_input, None, out["audio"], memory)
        return respond(handler_input, answer, end=out["end"], permissions=out["missing"])


class BriefingHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("BriefingIntent")(handler_input)

    def handle(self, handler_input):
        """Resumen del día sin IA: clima, dólar, pendientes y feriado cercano, todo a la vez (~1 s)."""
        inicio = time.time()
        n = now_local()
        saludo = "Buenas noches" if n.hour < 6 or n.hour >= 20 else "Buen día" if n.hour < 13 else "Buenas tardes"
        pool = ThreadPoolExecutor(max_workers=5)
        conectada = bool(pc_link()[0])
        tareas = {"clima": pool.submit(clima), "dolar": pool.submit(_dolar_blue),
                  "agenda": pool.submit(send_to_pc, "agenda", {"cuando": "hoy"}, 3.0) if conectada else None,
                  "pendientes": pool.submit(send_to_pc, "pendientes", {}, 2.5) if conectada else None,
                  "feriado": pool.submit(proximo_feriado)}
        partes = [f"{saludo}. Son las {n.hour}:{n.minute:02d}."]
        for clave in ("clima", "agenda", "dolar", "pendientes", "feriado"):
            futuro = tareas.get(clave)
            if not futuro:
                continue
            try:
                r = futuro.result(timeout=max(0.2, 3.5 - (time.time() - inicio)))
            except Exception as e:
                logger.warning("resumen %s: %s", clave, e)
                continue
            if clave in ("pendientes", "agenda"):
                r = r.get("texto") if r and r.get("ok") else None
            if clave == "agenda" and r and "no conectaste" in r:
                r = None                          # sin calendario conectado no se menciona
            if clave == "feriado" and r and not re.search(r"\ben [1-7] días\b|\bhoy\b|\bmañana\b", r):
                r = None                          # el feriado solo si es esta semana
            if r:
                partes.append(r)
        pool.shutdown(wait=False)
        texto = " ".join(partes)
        handler_input.attributes_manager.session_attributes["ultima"] = texto
        return respond(handler_input, texto)


class HelpHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        return respond(handler_input,
                       "Puedes preguntarme cualquier cosa, pedirme que anote ideas o pendientes, que abra algo en tu PC, "
                       "o que investigue un tema y te mande el resultado al celular.")


class StopHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (is_intent_name("AMAZON.StopIntent")(handler_input)
                or is_intent_name("AMAZON.CancelIntent")(handler_input))

    def handle(self, handler_input):
        if soporta_audio(handler_input):     # si suena la radio, que se calle
            handler_input.response_builder.add_directive(StopDirective())
        return respond(handler_input, "Hasta luego.", end=True)


class FallbackHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        return respond(handler_input, "No te entendí. ¿Puedes decirlo de otra forma?")


class SessionEndedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class ErrorHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.exception(exception)
        return respond(handler_input, "Lo siento, algo salió mal.")


class AudioEventosHandler(AbstractRequestHandler):
    """Eventos del reproductor (la radio): empezó, terminó, pausa y play desde el Echo o la app."""
    def can_handle(self, handler_input):
        tipo = str(getattr(handler_input.request_envelope.request, "object_type", "") or "")
        return tipo.startswith(("AudioPlayer.", "PlaybackController."))

    def handle(self, handler_input):
        tipo = str(handler_input.request_envelope.request.object_type)
        rb = handler_input.response_builder
        if tipo == "PlaybackController.PauseCommandIssued":
            rb.add_directive(StopDirective())
        elif tipo == "PlaybackController.PlayCommandIssued":
            radio = load_memory(handler_input).get("radio")
            if radio:
                rb.add_directive(_directiva_radio(radio))
        elif tipo == "AudioPlayer.PlaybackFailed":
            logger.warning("la radio falló: %s", handler_input.request_envelope.request)
        return rb.response


def _actividad_echo(handler_input):
    """PLAYING, PAUSED, STOPPED... de la radio en el Echo ('' si no se sabe)."""
    try:
        ap = handler_input.request_envelope.context.audio_player
        return str(ap.player_activity.value) if ap and ap.player_activity else ""
    except Exception:
        return ""


def _musica_pc(handler_input, que):
    if not pc_link()[0]:
        return None
    tipo, texto = run_pc_action({"accion": "musica_control", "datos": {"accion": que}}, time.time() + 4.5)
    return respond(handler_input, texto or "Listo.")


class PausaHandler(AbstractRequestHandler):
    """"Alexa, pausa" / "Alexa, continuá": la radio del Echo si está sonando; si no, la música de la PC."""
    def can_handle(self, handler_input):
        return (is_intent_name("AMAZON.PauseIntent")(handler_input)
                or is_intent_name("AMAZON.ResumeIntent")(handler_input))

    def handle(self, handler_input):
        rb = handler_input.response_builder
        actividad = _actividad_echo(handler_input)
        if is_intent_name("AMAZON.ResumeIntent")(handler_input):
            radio = load_memory(handler_input).get("radio")
            if radio and soporta_audio(handler_input) and actividad in ("PAUSED", "STOPPED"):
                rb.add_directive(_directiva_radio(radio))
                return rb.set_should_end_session(True).response
            return _musica_pc(handler_input, "seguir") or respond(handler_input, "No hay nada para continuar.")
        if actividad == "PLAYING" or not pc_link()[0]:
            if soporta_audio(handler_input):
                rb.add_directive(StopDirective())
            return rb.set_should_end_session(True).response
        return _musica_pc(handler_input, "pausa")


class SiguienteHandler(AbstractRequestHandler):
    """"siguiente" / "anterior": pasa de tema en la música de la PC."""
    def can_handle(self, handler_input):
        return (is_intent_name("AMAZON.NextIntent")(handler_input)
                or is_intent_name("AMAZON.PreviousIntent")(handler_input))

    def handle(self, handler_input):
        que = "siguiente" if is_intent_name("AMAZON.NextIntent")(handler_input) else "anterior"
        return _musica_pc(handler_input, que) or respond(handler_input, "No hay música sonando en la PC.")


adapter = DynamoDbAdapter(
    table_name=os.environ.get("DYNAMODB_PERSISTENCE_TABLE_NAME"),
    create_table=False,
    dynamodb_resource=boto3.resource("dynamodb", region_name=os.environ.get("DYNAMODB_PERSISTENCE_REGION")),
)

sb = CustomSkillBuilder(persistence_adapter=adapter, api_client=DefaultApiClient())
for h in (AudioEventosHandler(), PausaHandler(), SiguienteHandler(), LaunchHandler(), BriefingHandler(), ChatHandler(), HelpHandler(),
          StopHandler(), FallbackHandler(), SessionEndedHandler()):
    sb.add_request_handler(h)
sb.add_exception_handler(ErrorHandler())

lambda_handler = sb.lambda_handler()
