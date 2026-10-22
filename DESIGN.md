---
name: Cerebro
description: Panel local de Cerebro, leído como la señalética del Subte de Buenos Aires.
colors:
  suelo: "#ffffff"
  chapa: "#ffffff"
  tenue: "#f2f2f0"
  tinta: "#161616"
  tinta-2: "#55575c"
  filete: "#dcdcda"
  filete-2: "#c4c5c3"
  banda: "#121212"
  banda-tinta: "#ffffff"
  banda-2: "#b9babd"
  linea-a: "#00aeef"
  linea-b: "#e30613"
  linea-c: "#0067b1"
  linea-d: "#00a650"
  linea-e: "#6f2c91"
  linea-h: "#ffd100"
  linea-p: "#6b6d72"
  ok: "#0b7f3b"
  demora: "#925400"
  corte: "#c8102e"
  apagado: "#6b6d72"
  ok-fondo: "#e5f4ea"
  demora-fondo: "#fbf0dc"
  corte-fondo: "#fbe5e8"
  foco: "#0067b1"
  suelo-oscuro: "#0f1011"
  chapa-oscuro: "#191a1c"
  tenue-oscuro: "#1d1e21"
  tinta-oscuro: "#ececea"
  tinta-2-oscuro: "#a4a6ab"
  filete-oscuro: "#2b2c30"
  filete-2-oscuro: "#3a3b40"
  ok-oscuro: "#45cf80"
  demora-oscuro: "#f2b347"
  corte-oscuro: "#ff6b70"
  apagado-oscuro: "#8d9096"
  ok-fondo-oscuro: "#12301f"
  demora-fondo-oscuro: "#33270f"
  corte-fondo-oscuro: "#3a1519"
  foco-oscuro: "#5cb8ff"
typography:
  display:
    fontFamily: "Bahnschrift, DIN Alternate, DIN 2014, Segoe UI, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 700
    lineHeight: 1
    letterSpacing: "0.01em"
  headline:
    fontFamily: "Bahnschrift, DIN Alternate, DIN 2014, Segoe UI, system-ui, sans-serif"
    fontSize: "17px"
    fontWeight: 600
    lineHeight: 1.2
    letterSpacing: "0.005em"
  title:
    fontFamily: "Bahnschrift, DIN Alternate, DIN 2014, Segoe UI, system-ui, sans-serif"
    fontSize: "15.5px"
    fontWeight: 600
    lineHeight: 1.25
  hora:
    fontFamily: "Bahnschrift, DIN Alternate, DIN 2014, Segoe UI, system-ui, sans-serif"
    fontSize: "16px"
    fontWeight: 600
    fontFeature: "tnum"
  body:
    fontFamily: "Segoe UI, system-ui, -apple-system, Roboto, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Segoe UI, system-ui, -apple-system, Roboto, sans-serif"
    fontSize: "13px"
    fontWeight: 600
  etiqueta:
    fontFamily: "Bahnschrift, DIN Alternate, DIN 2014, Segoe UI, system-ui, sans-serif"
    fontSize: "11.5px"
    fontWeight: 600
  mono:
    fontFamily: "Cascadia Mono, Consolas, ui-monospace, monospace"
    fontSize: "12.5px"
    fontWeight: 400
rounded:
  campo: "6px"
  mensaje: "8px"
  flotante: "10px"
  capsula: "999px"
  circulo: "50%"
spacing:
  xs: "8px"
  sm: "10px"
  md: "14px"
  lg: "22px"
  xl: "28px"
  contenedor: "1320px"
components:
  button:
    backgroundColor: "{colors.chapa}"
    textColor: "{colors.tinta}"
    typography: "{typography.label}"
    rounded: "{rounded.capsula}"
    padding: "6px 14px"
    height: "36px"
  button-primario:
    backgroundColor: "{colors.tinta}"
    textColor: "{colors.chapa}"
    rounded: "{rounded.capsula}"
    padding: "6px 14px"
    height: "36px"
  button-peligro:
    backgroundColor: "{colors.chapa}"
    textColor: "{colors.corte}"
    rounded: "{rounded.capsula}"
    padding: "6px 14px"
    height: "36px"
  button-lisa:
    textColor: "{colors.tinta-2}"
    rounded: "{rounded.capsula}"
    padding: "6px 14px"
  button-chico:
    rounded: "{rounded.capsula}"
    padding: "3px 10px"
    height: "30px"
  input:
    backgroundColor: "{colors.chapa}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.campo}"
    padding: "7px 11px"
    height: "38px"
  estacion:
    textColor: "{colors.tinta-2}"
    typography: "{typography.title}"
    padding: "8px 12px"
    height: "52px"
  estacion-activa:
    textColor: "{colors.tinta}"
  circulo:
    textColor: "#ffffff"
    rounded: "{rounded.circulo}"
    size: "28px"
  cuenta:
    backgroundColor: "{colors.tinta}"
    textColor: "{colors.chapa}"
    rounded: "{rounded.capsula}"
    padding: "1px 7px"
  etiqueta:
    backgroundColor: "{colors.tenue}"
    textColor: "{colors.tinta-2}"
    typography: "{typography.etiqueta}"
    rounded: "{rounded.capsula}"
    padding: "1px 8px"
  aviso-espera:
    backgroundColor: "{colors.demora-fondo}"
    textColor: "{colors.tinta}"
    rounded: "{rounded.capsula}"
    padding: "10px 12px 10px 10px"
  banda:
    backgroundColor: "{colors.banda}"
    textColor: "{colors.banda-tinta}"
    padding: "10px 24px"
    height: "58px"
---

# Design System: Cerebro

## Overview

**Creative North Star: "Señalética del Subte"**

Cerebro se lee como la señalética del Subte de Buenos Aires. Cada parte del sistema es una línea con su círculo de color, cada pestaña es una estación, y el estado se informa como el tablero de "estado del servicio" del andén: en palabras, con la hora en que empezó el cambio. El material es chapa esmaltada blanca bajo una banda negra de andén; los colores de línea son identidad pura y nunca significan estado.

La densidad es de panel de operación, pero calmada: una sola persona, una ventana grande de escritorio, poca información por pantalla. Los bloques no son tarjetas sino carteles: un rótulo en DIN sobre un filete de tinta de 2 px, y el contenido debajo sin fondo ni borde. Lo normal se muestra en tinta y gris; el color de estado aparece solo donde algo no anda.

Todo funciona sin internet: las caras son del sistema (Bahnschrift como DIN de señalética, Segoe UI para leer, Cascadia Mono para registros) y los íconos son un sprite SVG en línea dibujado a trazo.

**Key Characteristics:**
- Banda negra fija arriba con la marca, la frase de estado general y la hora.
- Ocho estaciones con círculo lleno de color de línea e ícono blanco a trazo.
- Bloques como carteles: filete de tinta de 2 px bajo el rótulo, sin chrome de tarjeta.
- Cápsulas planas para todo lo que se aprieta; campos con esquina chica.
- Estado en verde, ámbar o rojo, siempre con texto, solo en filas que no están sanas.
- Claro (chapa blanca) y oscuro (chapa grafito) con los mismos colores de línea.

## Colors

Neutros de chapa y tinta casi monocromos, siete colores de línea de identidad y una tríada de estado que solo aparece cuando hace falta.

### Primary
- **Tinta de cartel** (tinta): texto, rótulos, filete de 2 px bajo cada cartel, botón primario relleno, contador de pestaña y círculo de las filas sanas del tablero.
- **Banda de andén** (banda): fondo de la banda superior fija; lleva su propia tinta blanca (banda-tinta) y gris (banda-2) que no cambian con el tema.

### Secondary
Los colores de línea del Subte. Se asignan por sección mediante una variable local de color (`--c`) y llenan círculos, el subrayado de 4 px de la estación activa y el fogonazo de cambio del tablero.
- **Celeste Línea A** (linea-a): Inicio y sus carteles.
- **Rojo Línea B** (linea-b): Acciones.
- **Azul Línea C** (linea-c): Automatizaciones y horarios; también el color de los enlaces en claro.
- **Verde Línea D** (linea-d): Notas, pendientes y compras.
- **Violeta Línea E** (linea-e): Tareas de Claude Code.
- **Amarillo Línea H** (linea-h): Casa. Es el único círculo claro: su ícono va en tinta oscura (#161616), no en blanco.
- **Gris Premetro** (linea-p): Memoria (círculo lleno) y Registro (círculo vacío con anillo de 2.5 px).

### Tertiary
La tríada de estado, cada una con su fondo tenue. Valores separados para claro y oscuro (sufijo `-oscuro`).
- **Servicio normal** (ok / ok-fondo): interruptor encendido, círculo del aviso de resultado exitoso. En el tablero, una fila sana NO se pinta de verde.
- **Demora** (demora / demora-fondo): servicios degradados y avisos que esperan un "sí" (cápsula ámbar tenue con círculo ámbar).
- **Corte** (corte / corte-fondo): servicios caídos, botón peligroso, campo inválido, franja sin conexión, mensajes de error.
- **Apagado** (apagado): servicio desactivado; círculo vacío con anillo de 2 px.

### Neutral
- **Suelo** (suelo): fondo de página.
- **Chapa esmaltada** (chapa): fondo de controles, barra de estaciones, diálogos y aviso flotante. Igual al suelo en claro; un escalón más claro en oscuro.
- **Tenue** (tenue): banda de filas no sanas del tablero, fila de acción abierta, burbujas de la consola, registro.
- **Gris de rótulo** (tinta-2): texto secundario, placeholders, estaciones inactivas.
- **Filete fino** (filete): separadores de 1 px entre filas de listas.
- **Filete de control** (filete-2): borde de botones, campos y cápsulas de día; pista del interruptor apagado.
- **Foco** (foco): anillo de foco de 2 px con 2 px de separación.

### Named Rules
**The Line Is Identity Rule.** Los colores de línea dicen *dónde* estás, nunca *cómo* está algo. Un servicio caído es rojo de corte (#c8102e), no rojo de Línea B; un acceso rápido toma el color de la línea de su grupo.

**The Quiet Normal Rule.** En el tablero, lo sano va en tinta: círculo de tinta, estado en gris. Solo las filas que no están sanas ganan la banda tenue y el color de estado, y siempre con texto ("Falta vincular", "Interrumpido") además del color.

## Typography

**Display Font:** Bahnschrift (con DIN Alternate, DIN 2014, Segoe UI)
**Body Font:** Segoe UI (con system-ui, -apple-system, Roboto)
**Label/Mono Font:** Cascadia Mono (con Consolas, ui-monospace)

**Character:** La DIN de señalética rotula: marca, estaciones, carteles, nombres de servicio, horas, contadores y etiquetas. Segoe UI lee: párrafos, ayudas, formularios, mensajes. La mono queda guardada para el registro y el log.

### Hierarchy
- **Display** (700, 21px, 1): la marca "Cerebro" en la banda. Única aparición.
- **Headline** (600, 17px, 1.2): rótulo de cada cartel y cabecera de diálogo.
- **Title** (600, 15–15.5px, 1.25): estaciones, nombres de servicio en el tablero, nombres de acción.
- **Hora** (600, 16px, cifras tabulares): horas fijas de la columna de próximos horarios; el reloj de la banda usa el mismo trato a 15px.
- **Body** (400, 15px, 1.5): texto corrido; secundarios a 13–14px en tinta-2.
- **Label** (600, 13px, Segoe UI): rótulo encima de cada campo de formulario.
- **Etiqueta** (600, 11.5–12px, DIN): etiquetas en cápsula y contadores.
- **Mono** (400, 12.5px): registro, log, bloques preformateados.

### Named Rules
**The DIN Rotula Rule.** Si es un rótulo que se lee de un vistazo (nombre, hora, número, estado), va en DIN 600. Si es una frase que se lee, va en Segoe UI. Toda cifra que cambia usa cifras tabulares.

**The Offline Faces Rule.** Solo caras del sistema. Sin fuentes web, sin CDN: el panel tiene que andar sin internet.

## Layout

Contenedor centrado de 1320px máximo con 24px de margen lateral (14px en celular). Banda fija de 58px arriba y barra de estaciones fija debajo (52px de alto, subrayado de 4px). Inicio usa dos columnas 1.35fr / 1fr con 28px de separación; la columna derecha queda fija al hacer scroll (top 134px) como la columna de frecuencias. Otras pestañas usan dos columnas parejas o tres. El ritmo vertical entre carteles es de 28px; dentro de un cartel, 10px bajo el rótulo y 14px antes del contenido; las filas de lista tienen 9–11px de alto de relleno separadas por filete de 1px.

Bajo 980px todo pasa a una columna y la columna fija se suelta. Bajo 640px la banda esconde la hora y el nombre, las estaciones quedan solo como círculos (nombre visible para lector de pantalla) repartidas a lo ancho, y los accesos rápidos pasan a una columna.

## Elevation & Depth

Plano por definición. La profundidad se da con la banda negra, los filetes y la banda tenue de las filas que requieren atención. Hay una sola sombra real, la del aviso de resultado flotante, y un velo detrás del diálogo. Los anillos con `box-shadow: inset` (círculo vacío, campo inválido) son trazos, no elevación.

### Shadow Vocabulary
- **Flotante** (`box-shadow: 0 10px 30px rgba(0,0,0,.18)`): solo el aviso de resultado que aparece abajo a la derecha.
- **Velo de diálogo** (`background: rgba(10,10,10,.5)`): fondo detrás de un diálogo modal.

### Named Rules
**The Sign Not Card Rule.** Un bloque es un cartel: rótulo en DIN sobre filete de tinta de 2px, contenido sin fondo, sin borde y sin sombra. Nada de grillas de tarjetas iguales.

## Shapes

Tres formas: el círculo (identidad de línea, luz de estado, perilla del interruptor), la cápsula de 999px (todo lo que se aprieta, más avisos que esperan, etiquetas, contadores, días y la consola) y el rectángulo de esquina chica (campos a 6px, burbujas de consola a 8px, aviso flotante y diálogo a 10px). Los separadores son filetes: 2px de tinta bajo rótulos, 1px de filete entre filas. Íconos a trazo de 1.8 (2.1 dentro de círculos), puntas redondeadas, en cuadro de 24.

### Named Rules
**The Capsule Rule.** Si se aprieta, es cápsula. Si se escribe, es campo de 6px. No hay botones de esquina intermedia.

## Components

### Buttons
Cápsulas planas, firmes y sin adorno.
- **Shape:** cápsula completa (999px), 36px de alto, 600 a 14px, ícono y texto con 7px de separación.
- **Default:** chapa con borde de filete-2; al pasar el mouse el borde pasa a tinta.
- **Primario:** relleno de tinta con texto en chapa; al pasar, la tinta se mezcla 14% con el color de línea activo.
- **Peligro:** texto rojo de corte con borde de corte al 55%.
- **Lisa:** sin borde ni fondo, texto gris; al pasar gana borde y tinta.
- **Chico / Ícono:** 30px de alto para acciones de fila; 34px cuadrado para ícono solo.
- **Foco / Ocupado:** anillo de foco de 2px a 2px; deshabilitado a 50% con cursor de espera y un ícono que gira.

### Chips
- **Etiqueta:** cápsula tenue con filete, DIN 600 11.5px; variante peligro en corte sobre corte-fondo.
- **Cuenta:** cápsula de tinta junto al nombre de la estación; se esconde vacía.
- **Días:** cápsulas con casilla; marcada pasa a relleno de tinta.

### Cards / Containers
- **Corner Style:** ninguno; el cartel no tiene caja.
- **Background:** transparente.
- **Shadow Strategy:** ninguna (ver Elevation & Depth).
- **Border:** filete de tinta de 2px bajo el rótulo, con un círculo de línea de 24px a la izquierda.
- **Internal Padding:** 10px bajo el rótulo, 14px antes del contenido.

### Inputs / Fields
- **Style:** chapa con borde de 1px filete-2, esquina de 6px, 38px de alto; al pasar el borde pasa a tinta-2. La consola "Pedile algo" usa el campo en cápsula.
- **Focus:** anillo de foco de 2px con 2px de separación.
- **Error / Disabled:** inválido con borde y anillo de 1px en rojo de corte; obligatorios con asterisco rojo.
- **Interruptor:** pista en cápsula de 44 por 26; encendido en verde ok, perilla blanca circular.

### Navigation
- **Estaciones:** ocho pestañas en DIN 600 15px sobre chapa, cada una con su círculo lleno de 28px e ícono blanco. Inactiva en tinta-2; al pasar, subrayado de filete-2; activa en tinta con subrayado de 4px del color de su línea. En celular quedan solo los círculos.
- **Banda de andén:** negra, fija, con la marca en disco blanco, la luz de estado (10px) y la frase general, la hora en cifras tabulares y el botón de tema.

### Estado del servicio (Signature Component)
El tablero del andén. Cada servicio (agente, internet, Telegram, Gemini, Claude Code, agenda, Gmail, disco) es una fila: círculo de 32px, nombre en DIN 600 15.5px con detalle en gris debajo, y el estado alineado a la derecha. Fila sana: círculo de tinta, estado en gris. Fila en demora o corte: banda tenue de 6px de esquina que sangra 12px a los lados, círculo y texto en el color de estado, y debajo "desde las HH:MM" marcando cuándo empezó. Apagado: círculo vacío con anillo gris. Cuando un estado cambia, la fila hace una sola vez el fogonazo `cambio`: fondo del color de la fila al 30% que se apaga en 1.6s con `cubic-bezier(.16,1,.3,1)`.

### Aviso que espera
Cápsula ámbar tenue con círculo de demora e ícono de alerta, la pregunta en el medio y los botones a la derecha. Va arriba de todo en Inicio.

## Do's and Don'ts

### Do:
- **Do** asignar a cada sección nueva un color de línea por `--c` y usarlo en su círculo y en el subrayado de su estación.
- **Do** rotular cada bloque como cartel: círculo de línea de 24px, rótulo DIN 600 17px, filete de tinta de 2px.
- **Do** informar estado con palabra y color juntos, y marcar con "desde las HH:MM" cuándo empezó un cambio.
- **Do** dibujar íconos nuevos en el sprite SVG en línea, a trazo de 1.8 en cuadro de 24, blancos sobre círculo lleno (tinta oscura sobre Línea H).
- **Do** usar cifras tabulares para toda hora, contador o número que se actualiza.
- **Do** respetar `prefers-reduced-motion`: sin transiciones ni el fogonazo de cambio.

### Don't:
- **Don't** usar un color de línea para comunicar estado, ni verde/ámbar/rojo de estado como identidad de una sección.
- **Don't** pintar de verde las filas sanas del tablero; lo normal va en tinta.
- **Don't** convertir los bloques en tarjetas con fondo, borde, esquina o sombra; la única sombra es la del aviso flotante.
- **Don't** cargar fuentes web ni recursos externos.
- **Don't** usar botones de esquina recta o intermedia; lo que se aprieta es cápsula.
- **Don't** usar íconos de fuente, emoji o caracteres como íconos.
