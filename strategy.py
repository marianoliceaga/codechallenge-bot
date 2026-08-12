"""Motor de juego para Connect 4.

El server manda el tablero como string y espera de vuelta un numero de columna.
Como el formato exacto no esta documentado, `parse_board` es deliberadamente
tolerante: acepta filas separadas por saltos de linea o por '|', ignora los '|'
que sean separadores de celda y toma como vacia cualquier celda en EMPTY_CHARS.

La orientacion (si la fila 0 es la de arriba o la de abajo) se deduce del propio
tablero, porque en Connect 4 las fichas se apilan contra el lado de la gravedad.
Internamente siempre se trabaja con la fila 0 arriba.
"""

import time

EMPTY = '.'
EMPTY_CHARS = frozenset('.-_ 0*')
WIN_LENGTH = 4

# Presupuesto por jugada. El server penaliza si el turno se vence, asi que la
# busqueda se corta por reloj y no solo por profundidad.
MAX_DEPTH = 6
TIME_BUDGET = 0.8

WIN_SCORE = 10 ** 6
INF = float('inf')

# Pesos de la heuristica. Bloquear vale un poco mas que atacar: si empatan,
# preferimos cortar la amenaza del rival.
SCORE_THREE = 100
SCORE_TWO = 10
SCORE_OPPONENT_THREE = -120
SCORE_OPPONENT_TWO = -12
SCORE_CENTER = 6


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


def _windows(grid):
    """Todas las ventanas de WIN_LENGTH celdas: horizontal, vertical y diagonales."""
    height, width = len(grid), len(grid[0])
    for row in range(height):
        for col in range(width):
            for d_row, d_col in ((0, 1), (1, 0), (1, 1), (1, -1)):
                end_row = row + d_row * (WIN_LENGTH - 1)
                end_col = col + d_col * (WIN_LENGTH - 1)
                if 0 <= end_row < height and 0 <= end_col < width:
                    yield [
                        grid[row + d_row * i][col + d_col * i]
                        for i in range(WIN_LENGTH)
                    ]


def evaluate(grid, me, opponent):
    """Puntaje del tablero desde el punto de vista de `me`."""
    score = 0
    for window in _windows(grid):
        mine = window.count(me)
        theirs = window.count(opponent)
        empty = window.count(EMPTY)
        if theirs == 0:
            if mine == 3 and empty == 1:
                score += SCORE_THREE
            elif mine == 2 and empty == 2:
                score += SCORE_TWO
        elif mine == 0:
            if theirs == 3 and empty == 1:
                score += SCORE_OPPONENT_THREE
            elif theirs == 2 and empty == 2:
                score += SCORE_OPPONENT_TWO

    center = len(grid[0]) // 2
    for row in grid:
        if row[center] == me:
            score += SCORE_CENTER
        elif row[center] == opponent:
            score -= SCORE_CENTER
    return score


def _ordered_columns(columns, width):
    """Del centro hacia afuera: mejora las podas de alpha-beta."""
    center = (width - 1) / 2
    return sorted(columns, key=lambda col: abs(col - center))


class _TimeUp(Exception):
    """Se acabo el presupuesto: la profundidad a medio explorar se descarta."""


def _negamax(grid, me, opponent, depth, alpha, beta, deadline):
    if time.monotonic() >= deadline:
        raise _TimeUp

    columns = valid_columns(grid)
    if not columns:
        return 0

    for col in columns:
        row = _landing_row(grid, col)
        grid[row][col] = me
        immediate = _is_win(grid, row, col, me)
        grid[row][col] = EMPTY
        if immediate:
            return WIN_SCORE + depth

    if depth == 0:
        return evaluate(grid, me, opponent)

    best = -INF
    for col in _ordered_columns(columns, len(grid[0])):
        row = _landing_row(grid, col)
        grid[row][col] = me
        try:
            score = -_negamax(
                grid, opponent, me, depth - 1, -beta, -alpha, deadline
            )
        finally:
            grid[row][col] = EMPTY
        best = max(best, score)
        alpha = max(alpha, score)
        if alpha >= beta:
            break
    return best


def best_column(grid, me, opponent, max_depth=MAX_DEPTH,
                time_budget=TIME_BUDGET):
    """Mejor columna segun negamax con profundizacion iterativa.

    Una profundidad solo cuenta si se termino de explorar: si se corta por
    reloj a mitad de camino, los puntajes no son comparables entre si (unos
    salen de mirar mas lejos que otros) y vale el resultado de la anterior.
    """
    columns = _ordered_columns(valid_columns(grid), len(grid[0]))
    if not columns:
        raise BoardError('no hay columnas disponibles')

    deadline = time.monotonic() + time_budget
    best = columns[0]
    for depth in range(1, max_depth + 1):
        best_at_depth, alpha = None, -INF
        try:
            for col in columns:
                row = _landing_row(grid, col)
                grid[row][col] = me
                try:
                    if _is_win(grid, row, col, me):
                        score = WIN_SCORE + depth
                    else:
                        score = -_negamax(
                            grid, opponent, me, depth - 1, -INF, -alpha,
                            deadline
                        )
                finally:
                    grid[row][col] = EMPTY
                if best_at_depth is None or score > alpha:
                    best_at_depth, alpha = col, score
        except _TimeUp:
            break
        best = best_at_depth
        # Un mate encontrado no mejora con mas profundidad.
        if alpha >= WIN_SCORE:
            break
    return best


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
        me = (side or '').strip()[:1] or '?'
        return best_column(
            grid, me, infer_opponent(grid, me), max_depth, time_budget
        )
    except (BoardError, IndexError, TypeError) as e:
        print('no pude leer el tablero ({}), juego la columna 0'.format(e))
        return 0
