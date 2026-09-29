# Contribuir a Cerebro

Cerebro es una skill personal que se volvió pública. Las contribuciones que más valen son las
que salen de usarla de verdad: una frase que no entendió, un dato argentino que falta, algo que
tardó de más.

## Antes de escribir código

- **Bug:** abrí un issue con la frase exacta que dijiste, lo que respondió y lo que esperabas.
- **Función nueva:** abrí un issue primero. Cada acción nueva compite por los ocho segundos que da
  Alexa; no todo lo que se puede agregar conviene.

## Dónde va cada cosa

- **Una vía rápida nueva** (responder sin IA): `via_rapida()` / `info_rapida()` en
  `lambda/lambda_function.py`. Regex tolerante a cómo se habla, no a cómo se escribe.
- **Una acción nueva que ejecuta la skill:** agregala a `run_actions()` y documentala en `PERSONA`,
  que es lo que le dice al modelo que existe.
- **Una acción nueva de PC:** va en `PC_ACTIONS` del lado de la skill y en el agente `pc/`.
- **Una fuente de datos nueva:** sin clave, con timeout corto (≤ 2,5 s) y que falle en silencio.

## Reglas de la casa

- **Nada de claves en el repo.** `lambda/config.py` y `pc/config.json` están en `.gitignore`;
  el CI falla si detecta una clave real.
- **Todo lo que se dice se escucha.** Sin markdown, sin listas, sin emojis en las respuestas.
  Números escritos como se pronuncian.
- **Presupuesto de tiempo.** Cualquier llamada de red nueva entra dentro de `ALEXA_BUDGET`. Si
  puede tardar, va en paralelo o con `aviso_progresivo()`.
- **Lo peligroso pide confirmación.** Apagar, mandar mensajes, borrar: siempre "¿Seguro?".

## Flujo

1. Rama desde `main`.
2. `python -m compileall lambda pc` y `ruff check lambda pc` tienen que pasar.
3. Probalo en tu propia skill (la consola de Alexa tiene un simulador en la pestaña *Test*).
4. Commits en formato [Conventional Commits](https://www.conventionalcommits.org/es/).
5. PR con la plantilla completa y, si es una vía rápida, las frases que probaste.
