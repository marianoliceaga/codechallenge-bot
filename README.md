# codechallenge-bot

[![tests](https://github.com/marianoliceaga/codechallenge-bot/actions/workflows/tests.yml/badge.svg)](https://github.com/marianoliceaga/codechallenge-bot/actions/workflows/tests.yml)

Bot cliente para [CodeChallenge](https://codechallenge.net.ar/). Se conecta por
websocket a `wss://server.codechallenge.net.ar/ws`, acepta desafíos y juega
**Snake** de a dos, por turnos, con las reglas de
[How to play](https://codechallenge-snake-production.up.railway.app/how-to-play)
vigentes al 7 Oct 2026 (v7).

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
| `strategy.py` | El motor de Snake: parseo del tablero, reglas y búsqueda. |
| `test_run.py` | Tests del cliente, con un websocket falso (no toca la red). |
| `test_strategy.py` | Tests del motor. |
| `requirements.txt` | Dependencia de runtime (`websockets`). |
| `requirements-dev.txt` | Lo anterior + `coverage` y `flake8`. |
| `.coveragerc` | Qué se mide y el umbral mínimo. |
| `setup.cfg` | Config de flake8. |

## La estrategia

Cada `your_turn` se contesta con

```json
{"action": "move", "data": {"game_id": "...", "turn_token": "...", "direction": "up"}}
```

y `strategy.choose_direction(turn_data)` elige la dirección. Todo se lee del
`board` (y de `rows`/`cols`, `remaining_moves`, `side`, `score_1/2` y
`multiplier_1/2`): el tamaño cambia de partida en partida (12 a 20 por lado, no
necesariamente cuadrado), así que nada está fijo en 15×15.

### Las reglas que modela (v1 a v7)

| Qué | Cómo lo toma el bot |
| --- | --- |
| Chocar (borde, cuerpo propio o ajeno, `#`) | Desde la v7 no termina la partida: la víbora queda quieta con cabeza + 2 celdas y el resto del cuerpo pasa a ser comida de cola para el rival. El **primer** choque deja el puntaje en 0 (si era positivo); los siguientes, -500. Solo choca si no queda otra, y un encierro le cuesta lo que le costaría ese choque: con mucho puntaje en juego se cuida más. |
| Comida de cola `Ⓐ` / `Ⓑ` | La letra dice quién la puede comer: +100 × multiplicador y crece. La del rival la puede pisar para borrarla (sin puntos), y eso también lo cuenta. |
| Bajar de -2500 | Pierde la partida. |
| Comida numerada `1`..`9` | Toca el dígito cuyo predecesor cíclico **no** está en el tablero (con `1 6 7 8 9` toca el 6, no el 1). El correcto vale `dígito × 100 × multiplicador` y hace crecer; otro cualquiera es -500 y lo esquiva. |
| Copias (v6) | Cada dígito está en 3 a 5 celdas. Va a la copia más cercana del que toca; comer una se lleva todas las demás, y una copia equivocada solo gasta esa (el server repone otra). |
| `X` | +50 y el multiplicador propio sube un escalón para siempre. Vale más cuanto antes se agarre. |
| `#` | Desde la v7 pegarle es un choque como cualquier otro. Se achica cada ronda. |
| +1 por jugada y `remaining_moves` | La búsqueda no mira más allá del final; en la última jugada gana el que tiene más puntos. Desde la v7 las partidas son de 400 jugadas. |
| `*` (reglas viejas) | Se sigue entendiendo como comida de 100. |

Se asume que el lado `A` es `player_1` (`score_1`, `multiplier_1`) y el `B`
`player_2`. Cualquier símbolo desconocido se trata como obstáculo.

### Cómo decide

**Minimax con poda alpha-beta y profundización iterativa**, cortada por reloj
(`TIME_BUDGET = 1.0` s). Cada jugada se simula con las reglas de arriba, y el
rival se supone el más molesto posible. Lo único que no se puede simular es lo
que aparece al azar (el dígito nuevo, la `X` de reemplazo, el muro siguiente).

En las hojas se evalúa:

- la diferencia de puntaje y la de multiplicadores (cada escalón vale más
  cuantas más jugadas quedan);
- la **carrera por la comida**: quién llega primero a alguna copia del dígito
  que toca, y desde ahí a los dos siguientes, así el que la pierde ya se
  acomoda para el próximo;
- las `X` y la comida de cola al alcance de cada uno, repartidas según la
  ventaja en distancia (no todo o nada: si no, pagaría penalidades por ganar
  un empate);
- el territorio (a qué celdas llega cada víbora antes que la otra) y si alguna
  quedó encerrada en menos lugar que su largo, valuado por lo que le costaría
  chocar: el puntaje que perdería y la cola que le serviría al otro. El BFS
  sabe que los cuerpos se van liberando desde la cola.

`turn_data` no dice quién ya chocó, y eso importa porque solo el primer choque
borra el puntaje. El bot lo recuerda por `game_id`: si entre dos turnos una
cabeza no se movió y su puntaje bajó, esa víbora chocó. También lo deduce si ve
en el tablero comida de cola que soltó alguien. Al terminar la partida
(`game_over`) se olvida.

El tablero no dice en qué orden van los segmentos, así que el cuerpo se
reconstruye buscando un camino desde la cabeza que pase por todas sus celdas.
