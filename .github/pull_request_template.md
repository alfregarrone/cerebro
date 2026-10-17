## Qué cambia

<!-- Una o dos frases. Si cierra un issue: "Cierra #123". -->

## Por qué

<!-- El problema que resuelve, no la descripción del diff. -->

## Cómo lo probaste

<!-- Tests agregados en tests/, frases que probaste en el simulador de Alexa o en el Echo, o ambos. -->

## Checklist

- [ ] `ruff check lambda pc pruebas tests` pasa
- [ ] `python -m pytest` pasa
- [ ] Agregué o actualicé tests en `tests/`
- [ ] Si agregué una acción de PC, está en `PC_ACTIONS` (skill), en `ACCIONES` (agente) y en el `CATALOGO` del panel
- [ ] Actualicé README / docs si hacía falta
