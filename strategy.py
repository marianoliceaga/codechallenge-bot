"""Motor de juego para Snake (reglas v5 de CodeChallenge, 23 Sep 2026).

Dos viboras, una por jugador, que mueven por turnos. El server manda el tablero
como string (filas envueltas en `|...|` y unidas por saltos de linea) y espera
de vuelta una direccion: `up`, `down`, `left` o `right`.

Lo que hay en el tablero y lo que vale:

- `A`/`B` cabezas, `a`/`b` cuerpos. Chocar contra el borde, un cuerpo o la
  otra vibora termina la partida: el que choca pierde.
- Comida numerada `1`..`9`: hay cinco digitos consecutivos (ciclicos, despues
  del 9 viene el 1) y hay que comerlos en orden. El que toca es el que no tiene
  a su predecesor en el tablero (con `1 6 7 8 9` toca el 6, no el 1). El
  correcto vale `digito * 100 * multiplicador` y hace crecer; cualquier otro
  es -500.
- `X`: +50 y el multiplicador propio sube un escalon para siempre. No crece.
- `#`: muro que se achica cada ronda. Pegarle es -500 y la vibora se queda
  quieta, pero la partida sigue (a veces es la unica salida que no mata).
- Cada movimiento que sobrevive suma +1. Si nadie choca, gana el que tiene mas
  puntos cuando se acaban los `remaining_moves` (cuentan las jugadas de los
  dos).
- `*` es la comida de las reglas viejas (+100); se sigue entendiendo por las
  dudas.

La decision sale de un minimax con poda alpha-beta y profundizacion iterativa
cortada por reloj. Los estados se simulan con las mismas reglas del server
(salvo lo que aparece al azar: comida, `X` y muros nuevos). En las hojas se
evalua:

- la diferencia de puntaje real y la de multiplicadores, valuada por las
  jugadas que quedan;
- la carrera por la comida: quien llega primero al digito que toca, y el que
  la pierde se acomoda cerca del siguiente;
- las `X` al alcance de cada uno;
- el territorio (celdas a las que cada vibora llega antes) y si alguna quedo
  encerrada en menos lugar que su largo. Para eso el BFS sabe que los cuerpos
  se van liberando desde la cola.
"""

import time

DIRECTIONS = {
    'up': (-1, 0),
    'right': (0, 1),
    'down': (1, 0),
    'left': (0, -1),
}
DEFAULT_DIRECTION = 'up'

# Contenido de una celda, ya normalizado. Las dos viboras se guardan como
# SNAKE: para chocar da lo mismo de quien es el cuerpo.
EMPTY = ' '
WALL = '#'
MULTIPLIER = 'X'
STAR = '*'
SNAKE = 's'
DIGITS = frozenset('123456789')
EMPTY_CHARS = frozenset(' .')
_BORDER_CHARS = frozenset('+-=')

# Reglamento.
MOVE_POINTS = 1
FOOD_POINTS = 100
MULTIPLIER_POINTS = 50
PENALTY = 500
DEFAULT_REMAINING_MOVES = 300

# La busqueda se corta por reloj. Al presupuesto hay que descontarle la ida y
# vuelta por el websocket: el server no espera para siempre.
TIME_BUDGET = 1.0
MAX_DEPTH = 32

WIN = 10 ** 6
INF = 10 ** 9
_DECIDED = WIN - 10 ** 4   # por encima de esto el resultado ya esta decidido

# Pesos de la evaluacion.
GAMMA = 0.9                 # descuento por cada paso hasta un objetivo
MULT_VALUE_PER_MOVE = 10    # cuanto rinde un escalon de multiplicador por jugada
FOOD_CHAIN = 3              # cuantos digitos de la secuencia mira la carrera
TERRITORY_WEIGHT = 1        # por celda de territorio
TRAPPED = 5000              # encerrado en menos lugar que el propio largo
TRAPPED_PER_CELL = 200


class BoardError(ValueError):
    """El string del tablero no se pudo interpretar."""


def parse_board(board, cols=None):
    """Devuelve el tablero como lista de filas (fila 0 = arriba), sin los `|`.

    Solo se recortan los `|` de los costados: los espacios son celdas vacias.
    """
    text = (board or '').replace('\r', '')
    lines = text.split('\n')
    if len(lines) == 1 and '||' in text:
        lines = text.split('||')

    grid = []
    for line in lines:
        if not line or set(line) <= _BORDER_CHARS:
            continue
        if line.startswith('|'):
            line = line[1:]
        if line.endswith('|'):
            line = line[:-1]
        grid.append(line)

    if not grid:
        raise BoardError('tablero vacio')
    width = cols or max(len(row) for row in grid)
    if width <= 0:
        raise BoardError('tablero sin columnas')
    return [row[:width].ljust(width) for row in grid]


def next_digit(digit):
    return digit % 9 + 1


def previous_digit(digit):
    return (digit - 2) % 9 + 1


def target_digit(digits):
    """El digito que toca comer: el que no tiene a su predecesor en juego.

    Normalmente hay uno solo. Si por algo hubiera varios, gana el que arranca
    la racha mas larga (y a igualdad, el menor).
    """
    present = set(digits)
    starts = [d for d in present if previous_digit(d) not in present]
    if not starts:
        return None

    def run_length(d):
        n = 0
        while d in present and n < 9:
            n += 1
            d = next_digit(d)
        return n

    return max(starts, key=lambda d: (run_length(d), -d))


_NEIGHBORS = {}


def neighbors(rows, cols):
    """Vecinos ortogonales de cada celda, cacheados por tamano de tablero."""
    key = (rows, cols)
    if key not in _NEIGHBORS:
        table = []
        for r in range(rows):
            for c in range(cols):
                cells = []
                for dr, dc in DIRECTIONS.values():
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < cols:
                        cells.append(nr * cols + nc)
                table.append(tuple(cells))
        _NEIGHBORS[key] = tuple(table)
    return _NEIGHBORS[key]


def trace_body(head, cells, neigh, limit=20000):
    """Ordena el cuerpo de la cola a la cabeza.

    El tablero no dice el orden de los segmentos, asi que se busca un camino
    desde la cabeza que pase por todas las celdas del cuerpo (probando primero
    la celda con menos salidas, que casi nunca obliga a volver atras). Si el
    cuerpo esta tan enroscado que no aparece en `limit` pasos, se usa el camino
    mas largo encontrado y lo que sobra se pone del lado de la cola.
    """
    path = [head]
    seen = {head}
    best = [head]
    budget = [limit]

    def free_neighbors(cell):
        return [n for n in neigh[cell] if n in cells and n not in seen]

    def extend():
        if len(path) - 1 == len(cells):
            return True
        budget[0] -= 1
        if budget[0] < 0:
            return False
        options = free_neighbors(path[-1])
        options.sort(key=lambda n: len(free_neighbors(n)))
        for n in options:
            path.append(n)
            seen.add(n)
            if len(path) > len(best):
                best[:] = path
            if extend():
                return True
            path.pop()
            seen.discard(n)
        return False

    order = path if extend() else best + sorted(cells.difference(best))
    return tuple(reversed(order))


def _as_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class State:
    """Una posicion. El jugador 0 es el bot y el 1 el rival.

    `bodies` van de la cola a la cabeza. `digits` e `items` (las `X` y `*`) se
    comparten entre estados y solo se copian cuando alguien come.
    """

    __slots__ = ('rows', 'cols', 'grid', 'bodies', 'scores', 'mults',
                 'digits', 'items', 'target', 'plies_left', 'to_move',
                 'crashed')

    def __init__(self, rows, cols, grid, bodies, scores=(0, 0), mults=(1, 1),
                 digits=None, items=None, target=None,
                 plies_left=DEFAULT_REMAINING_MOVES, to_move=0):
        self.rows = rows
        self.cols = cols
        self.grid = list(grid)
        self.bodies = [tuple(b) for b in bodies]
        self.scores = list(scores)
        self.mults = list(mults)
        self.digits = dict(digits or {})
        self.items = dict(items or {})
        self.target = target
        self.plies_left = plies_left
        self.to_move = to_move
        self.crashed = None

    def copy(self):
        s = State.__new__(State)
        s.rows = self.rows
        s.cols = self.cols
        s.grid = self.grid[:]
        s.bodies = self.bodies[:]
        s.scores = self.scores[:]
        s.mults = self.mults[:]
        s.digits = self.digits
        s.items = self.items
        s.target = self.target
        s.plies_left = self.plies_left
        s.to_move = self.to_move
        s.crashed = self.crashed
        return s

    def head(self, player):
        body = self.bodies[player]
        return body[-1] if body else None


def build_state(turn_data):
    """Arma el `State` a partir del `turn_data` de un `your_turn`.

    Devuelve None si en el tablero no esta la cabeza propia. Se asume que el
    lado `A` es `player_1` (`score_1`, `multiplier_1`) y el `B` `player_2`.
    """
    rows_text = parse_board(turn_data.get('board'),
                            _as_int(turn_data.get('cols'), None))
    rows, cols = len(rows_text), len(rows_text[0])

    me = str(turn_data.get('side') or 'A').strip().upper()[:1]
    if me not in ('A', 'B'):
        me = 'A'
    sides = (me, 'B' if me == 'A' else 'A')

    grid = []
    heads = {}
    body_cells = {'A': set(), 'B': set()}
    digits = {}
    items = {}
    for r, line in enumerate(rows_text):
        for c, ch in enumerate(line):
            i = r * cols + c
            if ch in ('A', 'B'):
                heads.setdefault(ch, i)
                grid.append(SNAKE)
            elif ch in ('a', 'b'):
                body_cells[ch.upper()].add(i)
                grid.append(SNAKE)
            elif ch in DIGITS:
                digits.setdefault(int(ch), i)
                grid.append(ch)
            elif ch in (MULTIPLIER, STAR):
                items[i] = ch
                grid.append(ch)
            elif ch in EMPTY_CHARS:
                grid.append(EMPTY)
            else:
                # '#' o algo que no conocemos: mejor no pisarlo.
                grid.append(WALL)

    if me not in heads:
        return None

    neigh = neighbors(rows, cols)
    bodies = []
    for side in sides:
        if side in heads:
            bodies.append(trace_body(heads[side], body_cells[side], neigh))
        else:
            bodies.append(())

    numbers = tuple('1' if side == 'A' else '2' for side in sides)
    scores = [_as_int(turn_data.get('score_' + n), 0) for n in numbers]
    mults = [max(1, _as_int(turn_data.get('multiplier_' + n), 1)) for n in numbers]
    plies_left = _as_int(turn_data.get('remaining_moves'), DEFAULT_REMAINING_MOVES)

    return State(rows, cols, grid, bodies, scores, mults, digits, items,
                 target_digit(digits), max(1, plies_left))


def step(state, player, direction):
    """Aplica una jugada y devuelve el estado nuevo (el original no cambia).

    `direction=None` es pasar (solo para un rival que no esta en el tablero).
    Moverse sobre la propia cola se toma como choque: no sabemos si el server
    la corre antes o despues de mirar la colision, y mejor no averiguarlo.
    """
    s = state.copy()
    s.plies_left -= 1
    s.to_move = 1 - player
    body = state.bodies[player]
    if direction is None or not body:
        return s

    cols = state.cols
    r, c = divmod(body[-1], cols)
    dr, dc = DIRECTIONS[direction]
    r += dr
    c += dc
    if not (0 <= r < state.rows and 0 <= c < cols):
        s.crashed = player
        return s
    dest = r * cols + c
    cell = state.grid[dest]
    if cell == SNAKE:
        s.crashed = player
        return s
    if cell == WALL:
        s.scores[player] -= PENALTY
        return s

    s.scores[player] += MOVE_POINTS
    grow = False
    if cell in DIGITS:
        digit = int(cell)
        if digit == state.target:
            s.digits = dict(state.digits)
            s.digits.pop(digit, None)
            s.scores[player] += digit * FOOD_POINTS * state.mults[player]
            grow = True
            following = next_digit(digit)
            s.target = following if following in s.digits else None
        else:
            # El server lo vuelve a poner en otro lado. No sabemos donde, asi
            # que sigue en la secuencia con su celda vieja: si desapareciera,
            # comerlo "cortaria" la carrera y pareceria negocio.
            s.scores[player] -= PENALTY
    elif cell == MULTIPLIER or cell == STAR:
        s.items = dict(state.items)
        s.items.pop(dest, None)
        if cell == MULTIPLIER:
            s.scores[player] += MULTIPLIER_POINTS
            s.mults[player] += 1
        else:
            s.scores[player] += FOOD_POINTS * state.mults[player]
            grow = True

    grid = s.grid
    if grow:
        s.bodies[player] = body + (dest,)
    else:
        grid[body[0]] = EMPTY
        s.bodies[player] = body[1:] + (dest,)
    grid[dest] = SNAKE
    return s


def legal_moves(state, player):
    """Las jugadas que no chocan. Pegarle al muro `#` cuenta: no mata."""
    body = state.bodies[player]
    if not body:
        return [None]
    cols = state.cols
    r, c = divmod(body[-1], cols)
    moves = []
    for name, (dr, dc) in DIRECTIONS.items():
        nr, nc = r + dr, c + dc
        if 0 <= nr < state.rows and 0 <= nc < cols \
                and state.grid[nr * cols + nc] != SNAKE:
            moves.append(name)
    return moves


def _goal(state, player):
    """Hacia donde conviene ir a ojo, para ordenar las jugadas."""
    if state.target is not None and state.target in state.digits:
        return state.digits[state.target]
    for cell in state.items:
        return cell
    return None


def _children(state, player, moves):
    """(jugada, estado) ordenados de mas a menos prometedor para `player`."""
    goal = _goal(state, player)
    cols = state.cols
    before = state.scores[player]
    scored = []
    for move in moves:
        child = step(state, player, move)
        key = child.scores[player] - before
        head = child.head(player)
        if goal is not None and head is not None:
            hr, hc = divmod(head, cols)
            gr, gc = divmod(goal, cols)
            key -= abs(hr - gr) + abs(hc - gc)
        scored.append((key, move, child))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [(move, child) for _, move, child in scored]


def _free_times(state):
    """Celda de cuerpo -> cuantas jugadas faltan para que quede libre."""
    free = {}
    for body in state.bodies:
        for k, cell in enumerate(body):
            free[cell] = k + 1
    return free


def distances(state, player, free=None):
    """BFS desde la cabeza de `player`: (distancias, celdas alcanzables).

    Los cuerpos cuentan como libres cuando su segmento ya se habria corrido,
    siempre que haya lugar para dar vueltas mientras tanto. Los digitos se
    alcanzan pero no se atraviesan (comer el equivocado cuesta 500).
    """
    if free is None:
        free = _free_times(state)
    n = state.rows * state.cols
    dist = [-1] * n
    body = state.bodies[player]
    if not body:
        return dist, 0
    grid = state.grid
    neigh = neighbors(state.rows, state.cols)
    start = body[-1]
    dist[start] = 0
    frontier = [start]
    pending = {}
    waiting = set()
    area = 0
    d = 0
    while frontier or pending:
        d += 1
        reached = []
        for i in frontier:
            for j in neigh[i]:
                if dist[j] >= 0:
                    continue
                ch = grid[j]
                if ch == WALL:
                    continue
                if ch == SNAKE:
                    ready = free.get(j, INF)
                    if ready > d:
                        if j not in waiting and ready < INF and area >= ready - d:
                            waiting.add(j)
                            pending.setdefault(ready, []).append(j)
                        continue
                dist[j] = d
                area += 1
                if ch not in DIGITS:
                    reached.append(j)
        for j in pending.pop(d, ()):
            if dist[j] < 0:
                dist[j] = d
                area += 1
                reached.append(j)
        frontier = reached
    return dist, area


def _trapped(area, length):
    if length and area < length:
        return TRAPPED + TRAPPED_PER_CELL * (length - area)
    return 0


def _food_race(state, d0, d1, my_turn):
    """Valor esperado de los proximos digitos de la secuencia para el bot.

    La carrera se juega en orden: el que llega primero al digito que toca se lo
    come y sale desde ahi (a ojo, en distancia Manhattan) hacia el siguiente;
    el otro se va acercando al siguiente, pero no lo puede comer antes de que
    le toque.
    """
    if state.target is None:
        return 0
    cols = state.cols
    dist = (d0, d1)
    origin = [None, None]   # None: sale desde la cabeza (vale el BFS)
    clock = [0, 0]
    ready = 0
    value = 0.0
    digit = state.target
    for _ in range(FOOD_CHAIN):
        cell = state.digits.get(digit)
        if cell is None:
            break
        arrival = []
        for p in (0, 1):
            if origin[p] is None:
                a = dist[p][cell]
                if a < 0:
                    arrival.append(None)
                    continue
            else:
                r, c = divmod(origin[p], cols)
                cr, cc = divmod(cell, cols)
                a = clock[p] + abs(r - cr) + abs(c - cc)
            arrival.append(max(a, ready + 1))
        a0, a1 = arrival
        if a0 is None and a1 is None:
            break
        if a1 is None or (a0 is not None and (a0 < a1 or (a0 == a1 and my_turn))):
            winner, steps = 0, a0
        else:
            winner, steps = 1, a1
        points = digit * FOOD_POINTS * state.mults[winner] * GAMMA ** steps
        value += points if winner == 0 else -points
        origin[winner] = cell
        clock[winner] = ready = steps
        digit = next_digit(digit)
    return value


def final_score(state):
    diff = state.scores[0] - state.scores[1]
    if diff > 0:
        return WIN + diff
    if diff < 0:
        return -WIN + diff
    return 0


def evaluate(state):
    """Valor de una posicion para el jugador 0 (mas alto, mejor para el bot)."""
    free = _free_times(state)
    dist = (distances(state, 0, free), distances(state, 1, free))
    d0, area0 = dist[0]
    d1, area1 = dist[1]
    my_turn = state.to_move == 0
    sign = (1, -1)

    value = state.scores[0] - state.scores[1]
    mult_value = MULT_VALUE_PER_MOVE * state.plies_left / 2
    value += (state.mults[0] - state.mults[1]) * mult_value

    def first(cell):
        a, b = d0[cell], d1[cell]
        if a >= 0 and (b < 0 or a < b or (a == b and my_turn)):
            return 0, a
        if b >= 0:
            return 1, b
        return None, 0

    value += _food_race(state, d0, d1, my_turn)

    for cell, ch in state.items.items():
        winner, steps = first(cell)
        if winner is None:
            continue
        if ch == MULTIPLIER:
            gain = MULTIPLIER_POINTS + mult_value
        else:
            gain = FOOD_POINTS * state.mults[winner]
        value += sign[winner] * gain * GAMMA ** steps

    mine = theirs = 0
    for a, b in zip(d0, d1):
        if a >= 0 and (b < 0 or a < b or (a == b and my_turn)):
            mine += 1
        elif b >= 0:
            theirs += 1
    value += TERRITORY_WEIGHT * (mine - theirs)
    value -= _trapped(area0, len(state.bodies[0]))
    value += _trapped(area1, len(state.bodies[1]))
    return value


class _Timeout(Exception):
    pass


class _Searcher:
    def __init__(self, deadline):
        self.deadline = deadline
        self.nodes = 0

    def search(self, state, depth, alpha, beta, ply):
        if state.crashed is not None:
            return -WIN + ply if state.crashed == 0 else WIN - ply
        if state.plies_left <= 0:
            return final_score(state)
        if depth <= 0:
            return evaluate(state)
        self.nodes += 1
        if time.perf_counter() > self.deadline:
            raise _Timeout()

        player = state.to_move
        moves = legal_moves(state, player)
        if not moves:
            # No queda otra que chocar.
            return -WIN + ply + 1 if player == 0 else WIN - ply - 1

        if player == 0:
            best = -INF
            for _, child in _children(state, 0, moves):
                best = max(best, self.search(child, depth - 1, alpha, beta, ply + 1))
                alpha = max(alpha, best)
                if alpha >= beta:
                    break
            return best
        best = INF
        for _, child in _children(state, 1, moves):
            best = min(best, self.search(child, depth - 1, alpha, beta, ply + 1))
            beta = min(beta, best)
            if alpha >= beta:
                break
        return best


def best_direction(state, time_budget=TIME_BUDGET, max_depth=MAX_DEPTH):
    """Mejor jugada para el jugador 0 dentro del presupuesto de tiempo."""
    moves = legal_moves(state, 0)
    if not moves or moves == [None]:
        return DEFAULT_DIRECTION
    ordered = _children(state, 0, moves)
    best = ordered[0][0]
    if len(ordered) == 1:
        return best

    searcher = _Searcher(time.perf_counter() + time_budget)
    horizon = max(1, min(max_depth, state.plies_left))
    for depth in range(1, horizon + 1):
        scored = []
        try:
            alpha = -INF
            for move, child in ordered:
                value = searcher.search(child, depth - 1, alpha, INF, 1)
                scored.append((value, move, child))
                alpha = max(alpha, value)
        except _Timeout:
            # Si en la vuelta cortada algo ya supero a la mejor anterior
            # (que se busca primero), vale mas que lo de la vuelta pasada.
            if scored:
                top = max(scored, key=lambda x: x[0])
                if top[0] > scored[0][0]:
                    best = top[1]
            break
        scored.sort(key=lambda x: x[0], reverse=True)
        ordered = [(move, child) for _, move, child in scored]
        best = ordered[0][0]
        if abs(scored[0][0]) >= _DECIDED:
            break
    return best


def choose_direction(turn_data, time_budget=TIME_BUDGET, max_depth=MAX_DEPTH):
    """Punto de entrada: `turn_data` de un `your_turn` -> direccion."""
    try:
        state = build_state(turn_data)
    except BoardError:
        state = None
    if state is None:
        return DEFAULT_DIRECTION
    return best_direction(state, time_budget, max_depth)
