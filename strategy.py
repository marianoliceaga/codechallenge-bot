"""Motor de juego para Connect 4.

El server manda el tablero como string y espera de vuelta un numero de columna.
Como el formato exacto no esta documentado, `parse_board` es deliberadamente
tolerante: acepta filas separadas por saltos de linea o por '|', ignora los '|'
que sean separadores de celda y toma como vacia cualquier celda en EMPTY_CHARS.

La orientacion (si la fila 0 es la de arriba o la de abajo) se deduce del propio
tablero, porque en Connect 4 las fichas se apilan contra el lado de la gravedad.
Hacia afuera siempre se trabaja con la fila 0 arriba.

Para buscar, en cambio, el tablero se pasa a *bitboards*: dos enteros (las
fichas del que mueve y las de todos) con un bit por celda y una fila centinela
por columna, al estilo Fhourstones. Todo lo caro de la busqueda (detectar
lineas de 4, listar jugadas, medir amenazas) queda en un par de shifts y
`bit_count()`, y eso es lo que permite bajar 10 a 13 plies en 1.5 segundos en
vez de los 6 que daba la version sobre listas. Ojo con las mascaras negadas:
`~mask` da un entero negativo y en CPython operarlo cuesta varias veces mas que
un `board ^ mask`, que sobre subconjuntos del tablero es lo mismo.

Encima de eso hay negamax con alpha-beta, profundizacion iterativa, tabla de
transposicion, killer moves y las dos podas de Pascal Pons: si el rival tiene
dos amenazas jugables la posicion ya esta perdida, y jugar debajo de una
casilla ganadora del rival tambien pierde. Las dos reglas son exactas, asi que
valen aunque la busqueda se corte por profundidad, y hacen que el motor vea los
mates forzados mucho antes que el limite de la busqueda.
"""

import time

EMPTY = '.'
EMPTY_CHARS = frozenset('.-_ 0*')
WIN_LENGTH = 4

# La busqueda se corta por reloj, no por profundidad: MAX_DEPTH es solo el
# techo (un tablero de 7x6 se llena en 42 jugadas) y TIME_BUDGET es el que
# manda. Ojo al subirlo: el server penaliza si el turno se vence, y al
# presupuesto hay que descontarle la ida y vuelta por el websocket.
MAX_DEPTH = 42
TIME_BUDGET = 1.5

WIN_SCORE = 10 ** 6
INF = 10 ** 9

# Pesos de la heuristica de hojas.
SCORE_PLAYABLE_THREAT = 60   # amenaza que se puede completar en el acto
SCORE_THREAT = 18            # amenaza esperando a que se llene la columna
SCORE_PARITY = 24            # amenaza en una fila de la paridad que me sirve
SCORE_CENTER = 2             # por ficha y por banda de columnas

# Rangos del ordenamiento de jugadas, y desde que profundidad conviene pagar
# el ordenamiento fino (contar amenazas creadas).
_ORDER_TT = 1 << 20
_ORDER_KILLER = 1 << 19
_ORDER_THREAT = 1 << 8
_ORDER_MIN_DEPTH = 4

# Cada 1024 nodos se mira el reloj: mirarlo en cada nodo cuesta mas que buscar.
_TIME_CHECK_MASK = 1023

# Flags de la tabla de transposicion.
_EXACT, _LOWER, _UPPER = 0, 1, 2


class BoardError(ValueError):
    """El string del tablero no se pudo interpretar."""


def parse_board(board_str):
    """Devuelve el tablero como lista de filas (fila 0 = arriba)."""
    # Solo se recortan saltos de linea: un espacio puede ser una celda vacia.
    text = (board_str or '').strip('\r\n')
    if not text.strip():
        raise BoardError('tablero vacio')

    raw_rows = text.splitlines() if '\n' in text else text.split('|')

    grid = []
    for raw in raw_rows:
        cells = [
            EMPTY if char in EMPTY_CHARS else char
            for char in raw.replace('|', '').strip('\r')
        ]
        if cells:
            grid.append(cells)

    if not grid:
        raise BoardError('no se encontraron filas en {!r}'.format(board_str))

    width = len(grid[0])
    if any(len(row) != width for row in grid):
        raise BoardError('filas de distinto ancho en {!r}'.format(board_str))
    if len(grid) < WIN_LENGTH or width < WIN_LENGTH:
        raise BoardError(
            'tablero de {}x{}, muy chico para Connect 4'.format(
                len(grid), width
            )
        )

    if not _is_top_down(grid) and _is_top_down(grid[::-1]):
        grid.reverse()
    return grid


def _is_top_down(grid):
    """True si las fichas se apilan hacia abajo, que es como las guardamos.

    Con gravedad hacia abajo ninguna columna puede tener un hueco debajo de una
    ficha. Un tablero vacio (o lleno) cumple las dos orientaciones y se toma
    como esta.
    """
    for col in range(len(grid[0])):
        seen_piece = False
        for row in grid:
            if row[col] != EMPTY:
                seen_piece = True
            elif seen_piece:
                return False
    return True


def valid_columns(grid):
    return [col for col in range(len(grid[0])) if grid[0][col] == EMPTY]


def _landing_row(grid, col):
    """Fila donde caeria una ficha en `col`, o None si la columna esta llena."""
    for row in range(len(grid) - 1, -1, -1):
        if grid[row][col] == EMPTY:
            return row
    return None


def _is_win(grid, row, col, piece):
    """True si la ficha recien puesta en (row, col) cierra WIN_LENGTH en linea."""
    height, width = len(grid), len(grid[0])
    for d_row, d_col in ((0, 1), (1, 0), (1, 1), (1, -1)):
        count = 1
        for direction in (1, -1):
            r, c = row + d_row * direction, col + d_col * direction
            while (
                0 <= r < height
                and 0 <= c < width
                and grid[r][c] == piece
            ):
                count += 1
                r += d_row * direction
                c += d_col * direction
        if count >= WIN_LENGTH:
            return True
    return False


def winning_columns(grid, piece):
    """Columnas donde `piece` gana en el acto."""
    wins = []
    for col in valid_columns(grid):
        row = _landing_row(grid, col)
        grid[row][col] = piece
        if _is_win(grid, row, col, piece):
            wins.append(col)
        grid[row][col] = EMPTY
    return wins


def _ordered_columns(columns, width):
    """Del centro hacia afuera: mejora las podas de alpha-beta."""
    center = (width - 1) / 2
    return sorted(columns, key=lambda col: abs(col - center))


class _Geometry:
    """Mascaras fijas de un tablero de ancho x alto, calculadas una sola vez.

    Cada columna ocupa `height + 1` bits: la fila de arriba queda siempre en
    cero y hace de centinela, para que los desplazamientos no encadenen fichas
    de columnas vecinas. El bit de (col, fila) es `col * step + fila`, con la
    fila 0 abajo (al reves que la grilla, que se guarda con la 0 arriba).
    """

    __slots__ = (
        'width', 'height', 'step', 'bottom', 'board', 'column',
        'rows_first', 'rows_second', 'order', 'shifts', 'bands',
    )

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.step = height + 1
        self.bottom = sum(1 << (col * self.step) for col in range(width))
        self.board = self.bottom * ((1 << height) - 1)
        full = (1 << height) - 1
        self.column = [full << (col * self.step) for col in range(width)]
        # Una ficha vale mas cuanto mas al centro, porque entra en mas lineas
        # de 4. Las columnas se agrupan por distancia al medio y cada grupo
        # queda en una mascara, asi la evaluacion son unos pocos `bit_count`.
        bands = {}
        middle = (width - 1) / 2
        for col in range(width):
            weight = int(middle - abs(col - middle)) + 1
            bands[weight] = bands.get(weight, 0) | self.column[col]
        self.bands = tuple(sorted(bands.items()))
        # Teoria de paridad: al que abre la partida le sirven las amenazas de
        # las filas impares contando desde 1, o sea las de indice par.
        self.rows_first = sum(
            self.bottom << row for row in range(0, height, 2)
        )
        self.rows_second = sum(
            self.bottom << row for row in range(1, height, 2)
        )
        self.order = _ordered_columns(range(width), width)
        # Desplazamientos de la horizontal y las dos diagonales, ya
        # multiplicados: `_winning_spots` corre en el nucleo de la busqueda.
        self.shifts = tuple(
            (step, 2 * step, 3 * step)
            for step in (self.step - 1, self.step, self.step + 1)
        )


_GEOMETRIES = {}


def _geometry(width, height):
    geo = _GEOMETRIES.get((width, height))
    if geo is None:
        geo = _Geometry(width, height)
        _GEOMETRIES[(width, height)] = geo
    return geo


def _to_bitboards(grid, me):
    """Pasa la grilla a (fichas de `me`, fichas de todos, geometria).

    Cualquier ficha que no sea `me` cuenta como del rival, asi no importa si el
    server manda una tercera marca rara.
    """
    height, width = len(grid), len(grid[0])
    geo = _geometry(width, height)
    position = mask = 0
    for index, row in enumerate(grid):
        shift = height - 1 - index
        for col, cell in enumerate(row):
            if cell == EMPTY:
                continue
            bit = 1 << (col * geo.step + shift)
            mask |= bit
            if cell == me:
                position |= bit
    return position, mask, geo


def _winning_spots(position, mask, geo):
    """Casillas vacias donde `position` cerraria una linea de 4."""
    # Vertical: la casilla justo arriba de tres fichas apiladas.
    spots = (position << 1) & (position << 2) & (position << 3)
    # Horizontal y las dos diagonales. Los cuatro huecos posibles de cada linea
    # (los dos extremos y los dos del medio) salen de estas seis combinaciones.
    for one, two, three in geo.shifts:
        pair = (position << one) & (position << two)
        spots |= pair & (position << three)
        spots |= pair & (position >> one)
        pair = (position >> one) & (position >> two)
        spots |= pair & (position << one)
        spots |= pair & (position >> three)
    return spots & (geo.board ^ mask)


def _evaluate_bits(position, mask, geo, mine, theirs):
    """Puntaje de la posicion, visto por el que tiene que mover.

    `mine` y `theirs` son las casillas ganadoras de cada uno; se piden hechas
    porque la busqueda ya las tiene calculadas.
    """
    opponent = position ^ mask
    playable = (mask + geo.bottom) & geo.board

    # Amenazas que se completan en la jugada siguiente. Viniendo de la busqueda
    # las mias siempre dan cero (si tuviera una, el nodo ya habria devuelto
    # victoria), pero la cuenta se hace igual para los dos lados para que el
    # puntaje sea simetrico cuando se llama a `evaluate` desde afuera.
    score = SCORE_PLAYABLE_THREAT * (
        (mine & playable).bit_count() - (theirs & playable).bit_count()
    )
    score += SCORE_THREAT * (mine.bit_count() - theirs.bit_count())

    # Con las fichas empatadas no se sabe quien abrio la partida, y sin eso el
    # termino de paridad no significa nada.
    played, faced = position.bit_count(), opponent.bit_count()
    if played != faced:
        if played > faced:
            my_rows, their_rows = geo.rows_first, geo.rows_second
        else:
            my_rows, their_rows = geo.rows_second, geo.rows_first
        score += SCORE_PARITY * (
            (mine & my_rows).bit_count() - (theirs & their_rows).bit_count()
        )

    for weight, band in geo.bands:
        score += SCORE_CENTER * weight * (
            (position & band).bit_count() - (opponent & band).bit_count()
        )
    return score


def evaluate(grid, me, opponent=None):
    """Puntaje del tablero desde el punto de vista de `me`.

    `opponent` se acepta por compatibilidad: en los bitboards toda ficha que no
    sea `me` ya cuenta como del rival.
    """
    position, mask, geo = _to_bitboards(grid, me)
    return _evaluate_bits(
        position, mask, geo,
        _winning_spots(position, mask, geo),
        _winning_spots(position ^ mask, mask, geo),
    )


class _TimeUp(Exception):
    """Se acabo el presupuesto: la profundidad a medio explorar se descarta."""


class _Search:
    """Negamax con alpha-beta sobre bitboards.

    La tabla de transposicion dura una sola busqueda: los puntajes de mate se
    guardan relativos a la raiz, asi que reusarla en la jugada siguiente daria
    distancias corridas.
    """

    __slots__ = ('geo', 'deadline', 'table', 'killers', 'nodes', 'spots')

    def __init__(self, geo, deadline):
        self.geo = geo
        self.deadline = deadline
        self.table = {}
        self.killers = {}
        self.nodes = 0
        self.spots = {}

    def winning_spots(self, position, mask):
        """`_winning_spots` con memoria: la misma posicion se llega por muchos
        ordenes de jugadas distintos y el calculo es lo mas caro del nodo."""
        key = position + mask
        found = self.spots.get(key)
        if found is None:
            found = self.spots[key] = _winning_spots(position, mask, self.geo)
        return found

    def negamax(self, position, mask, depth, alpha, beta, ply,
                my_spots, their_spots):
        """Puntaje de la posicion para el que mueve.

        `my_spots` y `their_spots` son las casillas ganadoras de cada lado. Las
        arma el padre y bajan como parametro: despues de una jugada mia, las
        del rival son las mismas de antes menos la casilla que acabo de tapar,
        y las mias ya se calcularon al ordenar las jugadas. Recalcularlas en
        cada nodo era la mitad del costo de la busqueda.
        """
        self.nodes += 1
        if not self.nodes & _TIME_CHECK_MASK:
            if time.monotonic() >= self.deadline:
                raise _TimeUp

        geo = self.geo
        playable = (mask + geo.bottom) & geo.board
        if not playable:
            return 0  # tablero lleno: empate

        # Gano ya: no hace falta mirar mas abajo.
        if my_spots & playable:
            return WIN_SCORE - ply

        # Podas exactas: la posicion esta perdida valga lo que valga la
        # heuristica, asi que se aplican aunque `depth` ya sea 0.
        moves = playable
        forced = moves & their_spots
        if forced:
            if forced & (forced - 1):
                return ply + 1 - WIN_SCORE  # dos amenazas, no se tapan las dos
            moves = forced                  # una sola: taparla es obligatorio
        moves &= ~(their_spots >> 1)        # no dejarle la ganadora servida
        if not moves:
            return ply + 1 - WIN_SCORE

        if depth <= 0:
            return _evaluate_bits(position, mask, geo, my_spots, their_spots)

        key = position + mask
        tt_move = 0
        entry = self.table.get(key)
        if entry is not None:
            entry_depth, flag, value, tt_move = entry
            if entry_depth >= depth:
                if flag == _EXACT:
                    return value
                if flag == _LOWER:
                    alpha = max(alpha, value)
                else:
                    beta = min(beta, value)
                if alpha >= beta:
                    return value
        alpha_start, beta_start = alpha, beta

        order, column = geo.order, geo.column
        bits = [moves & column[col] for col in order]
        bits = [bit for bit in bits if bit]
        created = self._sort_moves(bits, position, mask, tt_move, ply, depth)

        best, best_move = -INF, 0
        child_position = position ^ mask
        for bit in bits:
            child_theirs = created.get(bit)
            if child_theirs is None:
                child_theirs = self.winning_spots(position | bit, mask | bit)
            score = -self.negamax(
                child_position, mask | bit, depth - 1, -beta, -alpha, ply + 1,
                their_spots & ~bit, child_theirs,
            )
            if score > best:
                best, best_move = score, bit
            if score > alpha:
                alpha = score
            if alpha >= beta:
                self.killers[ply] = bit
                break

        if best <= alpha_start:
            flag = _UPPER
        elif best >= beta_start:
            flag = _LOWER
        else:
            flag = _EXACT
        self.table[key] = (depth, flag, best, best_move)
        return best

    def _sort_moves(self, bits, position, mask, tt_move, ply, depth):
        """Ordena `bits` en el lugar y devuelve las amenazas ya calculadas.

        Cerca de la raiz conviene mirar cuantas amenazas crea cada jugada: son
        pocos nodos y un buen orden poda muchisimo. Mas abajo el calculo no se
        paga solo, y alcanza con la jugada de la tabla, la killer y el orden
        del centro hacia afuera con el que ya vienen.
        """
        if len(bits) < 2:
            return {}

        if depth >= _ORDER_MIN_DEPTH:
            killer = self.killers.get(ply, 0)
            created = {
                bit: self.winning_spots(position | bit, mask | bit)
                for bit in bits
            }

            def rank(bit):
                if bit == tt_move:
                    return _ORDER_TT
                if bit == killer:
                    return _ORDER_KILLER
                return _ORDER_THREAT * created[bit].bit_count()

            bits.sort(key=rank, reverse=True)
            return created

        first = tt_move or self.killers.get(ply, 0)
        if first in bits:
            bits.insert(0, bits.pop(bits.index(first)))
        return {}


def best_column(grid, me, opponent=None, max_depth=MAX_DEPTH,
                time_budget=TIME_BUDGET):
    """Mejor columna segun negamax con profundizacion iterativa.

    Una profundidad solo cuenta si se termino de explorar: si se corta por
    reloj a mitad de camino, los puntajes no son comparables entre si (unos
    salen de mirar mas lejos que otros) y vale el resultado de la anterior.
    """
    position, mask, geo = _to_bitboards(grid, me)
    playable = (mask + geo.bottom) & geo.board
    if not playable:
        raise BoardError('no hay columnas disponibles')

    moves = [
        (col, playable & geo.column[col])
        for col in geo.order
        if playable & geo.column[col]
    ]

    # Ganar en el acto no necesita busqueda.
    my_spots = _winning_spots(position, mask, geo)
    for col, bit in moves:
        if my_spots & bit:
            return col

    their_spots = _winning_spots(position ^ mask, mask, geo)
    search = _Search(geo, time.monotonic() + time_budget)
    child_position = position ^ mask
    best = moves[0][0]
    # Mas alla de las casillas que quedan libres no hay arbol que explorar: la
    # ultima profundidad ya vio partidas terminadas y la respuesta es exacta.
    max_depth = min(max_depth, (geo.board ^ mask).bit_count())
    for depth in range(1, max_depth + 1):
        chosen, alpha = None, -INF
        try:
            for col, bit in moves:
                score = -search.negamax(
                    child_position, mask | bit, depth - 1, -INF, -alpha, 1,
                    their_spots & ~bit,
                    _winning_spots(position | bit, mask | bit, geo),
                )
                if chosen is None or score > alpha:
                    chosen, alpha = col, score
        except _TimeUp:
            break
        best = chosen
        # La proxima profundidad arranca por la mejor jugada de esta.
        moves.sort(key=lambda item: item[0] != best)
        if alpha >= WIN_SCORE - MAX_DEPTH:
            break  # mate encontrado: mas profundidad no lo mejora
    return best


def resolve_piece(grid, me):
    """Con que ficha jugamos, chequeando lo que dice el server contra el tablero.

    Si `side` no coincide con ninguna ficha puesta, tomarlo al pie de la letra
    seria fatal: el motor veria todas las fichas como del rival y jugaria en
    contra de si mismo. En ese caso se deduce por conteo, porque el que tiene
    que mover es siempre el que tiene menos fichas puestas.
    """
    counts = {}
    for row in grid:
        for cell in row:
            if cell != EMPTY:
                counts[cell] = counts.get(cell, 0) + 1

    if me in counts or len(counts) < 2:
        # Con una sola ficha en juego el tablero es consistente: somos el que
        # todavia no puso ninguna.
        return me
    return min(counts, key=lambda piece: (counts[piece], piece))


def infer_opponent(grid, me):
    """Ficha del rival, deducida del tablero. Cae en un placeholder al inicio."""
    for row in grid:
        for cell in row:
            if cell != EMPTY and cell != me:
                return cell
    return '?' if me != '?' else '!'


def choose_column(board_str, side, max_depth=MAX_DEPTH,
                  time_budget=TIME_BUDGET):
    """Columna a jugar. Nunca levanta: ante la duda juega la 0."""
    try:
        grid = parse_board(board_str)
        me = resolve_piece(grid, (side or '').strip()[:1] or '?')
        return best_column(
            grid, me, infer_opponent(grid, me), max_depth, time_budget
        )
    except (BoardError, IndexError, TypeError) as e:
        print('no pude leer el tablero ({}), juego la columna 0'.format(e))
        return 0
