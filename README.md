# codechallenge-bot

[![tests](https://github.com/marianoliceaga/codechallenge-bot/actions/workflows/tests.yml/badge.svg)](https://github.com/marianoliceaga/codechallenge-bot/actions/workflows/tests.yml)

Bot cliente para [CodeChallenge](https://codechallenge.net.ar/). Se conecta por
websocket a `wss://server.codechallenge.net.ar/ws`, acepta desafíos y juega su
turno.

## Correrlo

```bash
pip install -r requirements.txt
python run.py <tu_auth_token>
```

El `auth_token` se saca del perfil en https://codechallenge.net.ar/. **No lo
commitees**: `.gitignore` ya excluye `.env` y `token.txt`.

Cada partida terminada deja un `game_<game_id>.log` con los eventos recibidos
(`<`) y las acciones enviadas (`>`).

## Tests y coverage

```bash
pip install -r requirements-dev.txt
```

```bash
coverage run -m unittest discover -v
```

```bash
coverage report -m
```

`coverage html` genera el reporte navegable en `htmlcov/index.html`.

El umbral mínimo de cobertura está en `.coveragerc` (`fail_under = 90`): si baja
de ahí, `coverage report` devuelve error y la CI falla.

## Integración continua

`.github/workflows/tests.yml` corre en cada `push` y `pull_request`:

- **unittest**: matriz de Python 3.10 / 3.12 / 3.13, instala dependencias con
  caché de pip, corre los tests bajo `coverage` y publica el reporte en el
  resumen del job. En 3.12 además sube el HTML como artifact.
- **lint**: `flake8` sobre todo el repo (config en `setup.cfg`).

Ver el estado en la pestaña
[Actions](https://github.com/marianoliceaga/codechallenge-bot/actions).

## Estructura

| Archivo | Qué hace |
| --- | --- |
| `run.py` | El bot: conexión y loop de eventos. |
| `strategy.py` | El motor de Connect 4: parseo del tablero y búsqueda. |
| `test_run.py` | Tests del cliente, con un websocket falso (no toca la red). |
| `test_strategy.py` | Tests del motor. |
| `requirements.txt` | Dependencia de runtime (`websockets`). |
| `requirements-dev.txt` | Lo anterior + `coverage` y `flake8`. |
| `.coveragerc` | Qué se mide y el umbral mínimo. |
| `setup.cfg` | Config de flake8. |

## La estrategia

`strategy.choose_column()` decide la jugada con **negamax + poda alpha-beta y
profundización iterativa**, o sea que mira varias jugadas hacia adelante en vez
de tirar al azar:

- gana si tiene el 4 en línea disponible, y prefiere ganar antes que bloquear;
- bloquea la amenaza del rival;
- no juega columnas que le dejen servida la victoria al rival en la fila de
  arriba;
- si no hay táctica, valora el centro y las líneas de 2 y 3 abiertas.

La búsqueda se corta por reloj (`TIME_BUDGET`, 0.8 s) para no perder el turno
por timeout. Una profundidad solo se toma en cuenta si se terminó de explorar:
si se corta a mitad de camino vale el resultado de la anterior, porque si no se
estarían comparando puntajes que salen de mirar distinta cantidad de jugadas.

Contra el bot random del ejemplo gana **100 de 100** partidas, alternando quién
arranca.

Para ajustar la fuerza están `MAX_DEPTH` y `TIME_BUDGET`; los pesos de la
heurística son las constantes `SCORE_*`.

### Suposiciones sobre el tablero (verificar con una partida real)

El formato exacto del string del tablero no está documentado, así que
`parse_board()` es tolerante: acepta filas separadas por saltos de línea o por
`|`, toma como celda vacía cualquiera de `.-_ 0*`, y **deduce sola** si la fila
0 es la de arriba o la de abajo (en Connect 4 las fichas se apilan contra la
gravedad, así que el propio tablero lo delata). Si no lo puede interpretar,
avisa por consola y juega la columna 0.

Lo único que no se puede deducir es **con qué carácter se dibujan tus fichas**:
se asume que es el valor de `side` que manda el server. Después de la primera
partida real conviene mirar el `game_*.log` y confirmarlo; si no coincide, el
bot juega legal pero razona con los colores cambiados.
