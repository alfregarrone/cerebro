---
version: 1
slug: "pc-panel-html"
primary_target: "pc/panel.html"
related_targets: ["pc/panel.py"]
---

## Scope

Panel de la PC (`pc/panel.html`, servido por `pc/panel.py`). Modo: Operate. Una persona, ventana grande de escritorio; celular secundario. Tareas frecuentes con el mismo peso: ver estado y avisos, acciones rápidas, notas/pendientes/compras, automatizaciones y tareas. Evitar: lentitud o cuelgues, pantallas cargadas, aspecto de programador, cambiar de lugar las 8 pestañas.

## Direction contract

THESIS: Cerebro se lee como la señalética del Subte de Buenos Aires: cada parte del sistema es una línea con su círculo de color y el estado se informa como el tablero de "estado del servicio". Rechaza el tablero gris de tarjetas iguales con números grandes.

OWN-WORLD: Chapa esmaltada blanca y banda negra de andén; colores de línea A #00AEEF, B #E30613, C #0067B1, D #00A650, E #6F2C91, H #FFD100 como identidad (nunca como estado); estado en verde/ámbar/rojo con texto. Tipografía DIN de señalética (Bahnschrift) para rótulos y Segoe UI para lectura. Círculos llenos con ícono blanco dibujado, cápsulas planas, filetes de 2 px, sin sombras de adorno.

STORY: Abre el panel, ve en el tablero si todas las líneas tienen "servicio normal", atiende lo que espera su "sí", y hace lo que vino a hacer en uno o dos clics.

FIRST VIEWPORT: Banda negra arriba con "Cerebro", el estado general en una frase y la hora. Debajo, las 8 pestañas como estaciones con su círculo de línea. Inicio: izquierda, avisos que esperan respuesta y el tablero de estado del servicio (líneas con nombre y estado); derecha, accesos rápidos en grilla, la consola "Pedile algo" y los próximos horarios en columna fija como una frecuencia.

FORM: Señalética del Subte, posición 1 de mi lista (IMPECCABLE’S PICK). seed:6eec3d422a1f259e

Signature move: el tablero "Estado del servicio" — cada servicio (agente, internet, Telegram, Gemini, Claude Code, agenda, Gmail, disco) es una línea con su círculo y su estado; un cambio de estado se marca con la hora en que empezó.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance

## Unresolved

- Sin generación de imágenes: build code-led, el boceto elegido (`.impeccable/mocks/decision/model-pick.html`) es la referencia de crítica.
