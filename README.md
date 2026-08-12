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
| `run.py` | El bot: conexión, loop de eventos y estrategia de jugada. |
| `test_run.py` | Tests unitarios con un websocket falso (no toca la red). |
| `requirements.txt` | Dependencia de runtime (`websockets`). |
| `requirements-dev.txt` | Lo anterior + `coverage` y `flake8`. |
| `.coveragerc` | Qué se mide y el umbral mínimo. |
| `setup.cfg` | Config de flake8. |

## Dónde meter mano

La estrategia está en `process_move()`: hoy elige una columna al azar dentro del
ancho del tablero. Ahí va la lógica propia.
