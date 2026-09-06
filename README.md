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
profundización iterativa sobre bitboards**, o sea que mira una docena de
jugadas hacia adelante en vez de tirar al azar:

- gana si tiene el 4 en línea disponible, y prefiere ganar antes que bloquear;
- bloquea la amenaza del rival;
- no juega columnas que le dejen servida la victoria al rival en la fila de
  arriba;
- si no hay táctica, valora el centro, la cantidad de amenazas de cada lado y
  la **paridad** de las filas donde caen (en Connect 4 al que abre la partida le
  sirven las amenazas de las filas impares, y al segundo las pares).

### Cómo hace para mirar tan lejos

El tablero se busca en **bitboards**: dos enteros de Python (mis fichas y todas
las fichas) con un bit por celda y una fila centinela por columna, al estilo
Fhourstones. Detectar los 4 en línea, listar jugadas y contar amenazas pasa a
ser un puñado de shifts en vez de recorrer listas.

Encima de eso hay:

| Técnica | Para qué |
| --- | --- |
| Tabla de transposición | La misma posición se llega por muchos órdenes de jugadas; se calcula una sola vez. |
| Killer moves + orden por amenazas | Probar primero las jugadas buenas hace que alpha-beta pode muchísimo antes. |
| Amenazas heredadas del padre | Las máscaras de casillas ganadoras bajan como parámetro en vez de recalcularse en cada nodo. |
| Podas exactas de Pascal Pons | Si el rival tiene **dos** amenazas jugables la posición ya está perdida, y jugar debajo de una casilla ganadora del rival también pierde. |

Las dos podas de Pons son exactas, no heurísticas: valen aunque la búsqueda se
corte por profundidad. Por eso el motor encuentra mates forzados bastante más
lejos que el límite nominal de la búsqueda (por ejemplo ve un mate a 5 jugadas
buscando a profundidad 3).

Con esto, en los 1.5 s de `TIME_BUDGET` baja **10 plies en la apertura y 13 en
el medio juego**, a unos 170.000 nodos por segundo; en el final resuelve la
partida entera. La versión anterior, sobre listas de Python, llegaba a 6.

### Qué tan fuerte quedó

| Medición | Resultado |
| --- | --- |
| Contra el motor anterior, mismo tiempo por jugada (20 partidas, alternando quién abre) | **17-3** |
| Juego perfecto en tablero 4x4 (120 posiciones al azar contra un solucionador exacto por fuerza bruta) | 0 jugadas subóptimas |
| Ídem 5x4, dándole tiempo para llegar al final de la partida | 0 jugadas subóptimas |

Ese último punto es el que más dice: en un tablero donde la búsqueda **llega
hasta el final**, el motor juega perfecto, o sea que la búsqueda es correcta y
lo único que lo separa del juego perfecto en 7x6 es el presupuesto de tiempo.
El test `TestPlaysPerfectlyOnASmallBoard` deja esa comparación corriendo en
cada CI.

Un dato contraintuitivo que salió midiendo: probé una heurística de hojas más
rica (contar las ventanas de 4 todavía vivas, como hacía la versión anterior) y
**juega peor**, 6-14, porque evaluar sale caro y cuesta 3 plies de
profundidad. En este juego la profundidad le gana a la evaluación, así que la
heurística quedó deliberadamente barata.

La búsqueda se corta por reloj (`TIME_BUDGET`, 1.5 s) para no perder el turno
por timeout. Una profundidad solo se toma en cuenta si se terminó de explorar:
si se corta a mitad de camino vale el resultado de la anterior, porque si no se
estarían comparando puntajes que salen de mirar distinta cantidad de jugadas.

Para ajustar la fuerza está `TIME_BUDGET`: es lo que más rinde, porque cada vez
que se duplica el presupuesto entra aproximadamente un ply más de búsqueda.
**Ojo al subirlo**: el server penaliza el turno vencido, y al presupuesto hay
que descontarle la ida y vuelta por el websocket, así que conviene dejar
margen contra el timeout real del server. Los pesos de la heurística son las
constantes `SCORE_*`, y `MAX_DEPTH` es solo el techo (42, un tablero lleno).

### Suposiciones sobre el tablero (verificar con una partida real)

El formato exacto del string del tablero no está documentado, así que
`parse_board()` es tolerante: acepta filas separadas por saltos de línea o por
`|`, toma como celda vacía cualquiera de `.-_ 0*`, y **deduce sola** si la fila
0 es la de arriba o la de abajo (en Connect 4 las fichas se apilan contra la
gravedad, así que el propio tablero lo delata). Si no lo puede interpretar,
avisa por consola y juega la columna 0.

Lo único que no se puede deducir del todo es **con qué carácter se dibujan tus
fichas**: se arranca del valor de `side` que manda el server, pero
`resolve_piece()` lo cruza contra el tablero. Si `side` no coincide con ninguna
ficha puesta (por ejemplo el server manda `"red"` y el tablero viene con `X` y
`O`), se deduce por conteo: el que tiene que mover es siempre el que tiene
menos fichas. Sin ese chequeo el motor vería todas las fichas como del rival y
jugaría en contra de sí mismo, que es la única forma realista de que pierda.
Igual, después de la primera partida real conviene mirar el `game_*.log` y
confirmarlo.
