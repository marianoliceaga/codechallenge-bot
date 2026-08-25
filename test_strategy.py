import random
import unittest

import strategy


def board(*rows):
    return '\n'.join(rows)


def render(grid):
    """La grilla de vuelta al formato en que la manda el server."""
    return board(*[''.join(row) for row in grid])


EMPTY_BOARD = board(*['.......'] * 6)

# Presupuesto corto: los tests no necesitan la profundidad completa y asi la
# suite sigue siendo rapida.
FAST = {'time_budget': 0.1}


class TestParseBoard(unittest.TestCase):
    def test_rows_separated_by_newlines(self):
        grid = strategy.parse_board(EMPTY_BOARD)

        self.assertEqual(len(grid), 6)
        self.assertEqual(len(grid[0]), 7)

    def test_rows_separated_by_pipes(self):
        grid = strategy.parse_board('|' + '|'.join(['.......'] * 6) + '|')

        self.assertEqual(len(grid), 6)
        self.assertEqual(len(grid[0]), 7)

    def test_spaces_count_as_empty_cells(self):
        grid = strategy.parse_board(board(*['       '] * 5, 'AAA    '))

        self.assertEqual(len(grid), 6)
        self.assertEqual(len(grid[0]), 7)
        self.assertEqual(grid[5][0], 'A')
        self.assertEqual(grid[5][3], strategy.EMPTY)

    def test_pieces_end_up_at_the_bottom(self):
        grid = strategy.parse_board(board(*['.......'] * 5, 'A......'))

        self.assertEqual(grid[5][0], 'A')
        self.assertEqual(grid[0][0], strategy.EMPTY)

    def test_a_flipped_board_is_turned_around(self):
        """Si el server manda la fila 0 abajo, se normaliza."""
        grid = strategy.parse_board(board('A......', *['.......'] * 5))

        self.assertEqual(grid[5][0], 'A')

    def test_rows_of_different_width_are_rejected(self):
        with self.assertRaises(strategy.BoardError):
            strategy.parse_board(board('....', '.....', '....', '....'))

    def test_a_board_too_small_for_connect_4_is_rejected(self):
        with self.assertRaises(strategy.BoardError):
            strategy.parse_board('no es un tablero')

    def test_an_empty_string_is_rejected(self):
        with self.assertRaises(strategy.BoardError):
            strategy.parse_board('')

    def test_none_is_rejected(self):
        with self.assertRaises(strategy.BoardError):
            strategy.parse_board(None)

    def test_only_separators_is_rejected(self):
        with self.assertRaises(strategy.BoardError):
            strategy.parse_board('||||')


class TestValidColumns(unittest.TestCase):
    def test_all_columns_are_open_on_an_empty_board(self):
        grid = strategy.parse_board(EMPTY_BOARD)

        self.assertEqual(strategy.valid_columns(grid), list(range(7)))

    def test_a_full_column_is_not_offered(self):
        grid = strategy.parse_board(board(*['A......'] * 6))

        self.assertEqual(strategy.valid_columns(grid), list(range(1, 7)))

    def test_a_full_column_has_no_landing_row(self):
        grid = strategy.parse_board(board(*['A......'] * 6))

        self.assertIsNone(strategy._landing_row(grid, 0))
        self.assertEqual(strategy._landing_row(grid, 1), 5)


class TestWinDetection(unittest.TestCase):
    def test_finds_the_horizontal_win(self):
        grid = strategy.parse_board(board(*['.......'] * 5, 'AAA....'))

        self.assertEqual(strategy.winning_columns(grid, 'A'), [3])

    def test_finds_the_vertical_win(self):
        grid = strategy.parse_board(
            board('.......', '.......', '..A....', '..A....', '..A....',
                  '..B....')
        )

        self.assertEqual(strategy.winning_columns(grid, 'A'), [2])

    def test_finds_the_diagonal_win(self):
        """A tiene (5,0) (4,1) (3,2) y la col 3 esta justo a la altura."""
        grid = strategy.parse_board(
            board('.......', '.......', '.......', '..AB...', '.ABB...',
                  'ABBB...')
        )

        self.assertEqual(strategy.winning_columns(grid, 'A'), [3])

    def test_no_win_available(self):
        self.assertEqual(
            strategy.winning_columns(strategy.parse_board(EMPTY_BOARD), 'A'),
            [],
        )

    def test_winning_columns_leaves_the_board_untouched(self):
        grid = strategy.parse_board(board(*['.......'] * 5, 'AAA....'))

        strategy.winning_columns(grid, 'A')

        self.assertEqual(grid[5][3], strategy.EMPTY)


class TestChooseColumn(unittest.TestCase):
    def test_opens_in_the_center(self):
        self.assertEqual(strategy.choose_column(EMPTY_BOARD, 'A', **FAST), 3)

    def test_takes_the_win(self):
        self.assertEqual(
            strategy.choose_column(
                board(*['.......'] * 5, 'AAA....'), 'A', **FAST),
            3,
        )

    def test_blocks_the_opponent(self):
        self.assertEqual(
            strategy.choose_column(
                board(*['.......'] * 5, 'BBB....'), 'A', **FAST),
            3,
        )

    def test_winning_beats_blocking(self):
        self.assertEqual(
            strategy.choose_column(
                board('.......', '.......', '.......', '.......', 'AAA....',
                      'BBB....'),
                'A', **FAST),
            3,
        )

    def test_blocks_a_vertical_threat(self):
        self.assertEqual(
            strategy.choose_column(
                board('.......', '.......', '..B....', '..B....', '..B....',
                      '..A....'),
                'A', **FAST),
            2,
        )

    def test_does_not_hand_the_opponent_the_row_above(self):
        """Jugar la col 4 le da apoyo a B para completar .BBB arriba."""
        chosen = strategy.choose_column(
            board('.......', '.......', '.......', '.......', '.BBB...',
                  '.AAB...'),
            'A', **FAST)

        self.assertNotEqual(chosen, 4)

    def test_reads_the_pipe_separated_format(self):
        pipes = '|' + '|'.join(['.......'] * 5 + ['AAA....']) + '|'

        self.assertEqual(strategy.choose_column(pipes, 'A', **FAST), 3)

    def test_handles_a_flipped_board(self):
        flipped = board('BBB....', *['.......'] * 5)

        self.assertEqual(strategy.choose_column(flipped, 'A', **FAST), 3)

    def test_an_unreadable_board_falls_back_instead_of_raising(self):
        self.assertEqual(strategy.choose_column('???', 'A', **FAST), 0)

    def test_a_missing_side_still_returns_a_column(self):
        self.assertEqual(strategy.choose_column(EMPTY_BOARD, None, **FAST), 3)

    def test_never_picks_a_full_column(self):
        # columnas 0 a 5 llenas, solo queda la 6
        full = board(*['ABABAB.'] * 6)

        self.assertEqual(strategy.choose_column(full, 'A', **FAST), 6)

    def test_respects_the_time_budget(self):
        import time

        start = time.monotonic()
        strategy.choose_column(EMPTY_BOARD, 'A', time_budget=0.05)

        self.assertLess(time.monotonic() - start, 2)


class TestEvaluate(unittest.TestCase):
    def test_an_empty_board_is_balanced(self):
        grid = strategy.parse_board(EMPTY_BOARD)

        self.assertEqual(strategy.evaluate(grid, 'A', 'B'), 0)

    def test_my_three_in_a_row_scores_better_than_two(self):
        two = strategy.parse_board(board(*['.......'] * 5, 'AA.....'))
        three = strategy.parse_board(board(*['.......'] * 5, 'AAA....'))

        self.assertGreater(
            strategy.evaluate(three, 'A', 'B'),
            strategy.evaluate(two, 'A', 'B'),
        )

    def test_the_score_is_symmetric(self):
        grid = strategy.parse_board(board(*['.......'] * 5, 'AAB....'))

        self.assertEqual(
            strategy.evaluate(grid, 'A', 'B'),
            -strategy.evaluate(grid, 'B', 'A'),
        )

    def test_the_center_column_is_worth_more(self):
        center = strategy.parse_board(board(*['.......'] * 5, '...A...'))
        edge = strategy.parse_board(board(*['.......'] * 5, 'A......'))

        self.assertGreater(
            strategy.evaluate(center, 'A', 'B'),
            strategy.evaluate(edge, 'A', 'B'),
        )


class TestInferOpponent(unittest.TestCase):
    def test_reads_the_opponent_piece_off_the_board(self):
        grid = strategy.parse_board(board(*['.......'] * 5, 'AB.....'))

        self.assertEqual(strategy.infer_opponent(grid, 'A'), 'B')

    def test_falls_back_on_an_empty_board(self):
        grid = strategy.parse_board(EMPTY_BOARD)

        self.assertNotEqual(strategy.infer_opponent(grid, 'A'), 'A')


class TestBestColumn(unittest.TestCase):
    def test_a_full_board_has_no_answer(self):
        grid = strategy.parse_board(board(*['ABABABA'] * 6))

        with self.assertRaises(strategy.BoardError):
            strategy.best_column(grid, 'A', 'B')


class TestPlaysAWholeGame(unittest.TestCase):
    """El motor no debe elegir nunca una columna invalida."""

    def test_beats_a_left_most_opponent_without_illegal_moves(self):
        grid = strategy.parse_board(EMPTY_BOARD)
        rendered = '\n'.join(''.join(row) for row in grid)

        for turn in range(42):
            columns = strategy.valid_columns(grid)
            if not columns:
                break
            if turn % 2 == 0:
                col = strategy.choose_column(rendered, 'A', **FAST)
                self.assertIn(col, columns)
                piece = 'A'
            else:
                col = columns[0]
                piece = 'B'
            row = strategy._landing_row(grid, col)
            grid[row][col] = piece
            if strategy._is_win(grid, row, col, piece):
                self.assertEqual(piece, 'A', 'perdio contra un rival trivial')
                return
            rendered = '\n'.join(''.join(r) for r in grid)

        self.fail('la partida no termino en una victoria del motor')


class TestBitboards(unittest.TestCase):
    """El motor busca sobre bitboards, pero tiene que ver lo mismo que la
    version simple sobre la grilla."""

    def test_the_grid_survives_the_round_trip(self):
        grid = strategy.parse_board(
            board('.......', '.......', '.......', '...B...', '...A...',
                  '..BAA..')
        )
        position, mask, geo = strategy._to_bitboards(grid, 'A')

        # 3 fichas de A, 2 de B, y nada suelto en la fila centinela.
        self.assertEqual(position.bit_count(), 3)
        self.assertEqual((position ^ mask).bit_count(), 2)
        self.assertEqual(mask & ~geo.board, 0)

    def test_anything_that_is_not_mine_cuenta_como_del_rival(self):
        grid = strategy.parse_board(board(*['.......'] * 5, 'AXY....'))
        position, mask, _ = strategy._to_bitboards(grid, 'A')

        self.assertEqual(position.bit_count(), 1)
        self.assertEqual((position ^ mask).bit_count(), 2)

    def test_winning_spots_agree_with_the_grid_search(self):
        """Property test: en posiciones al azar, las casillas ganadoras
        jugables de los bitboards son las mismas columnas que encuentra
        `winning_columns` moviendo fichas en la grilla."""
        rng = random.Random(20260825)

        for _ in range(200):
            grid = [['.'] * 7 for _ in range(6)]
            for turn in range(rng.randint(0, 30)):
                columns = strategy.valid_columns(grid)
                if not columns:
                    break
                col = rng.choice(columns)
                grid[strategy._landing_row(grid, col)][col] = 'AB'[turn % 2]

            for piece in 'AB':
                position, mask, geo = strategy._to_bitboards(grid, piece)
                spots = strategy._winning_spots(position, mask, geo)
                playable = (mask + geo.bottom) & geo.board
                from_bits = [
                    col for col in range(7)
                    if spots & playable & geo.column[col]
                ]

                self.assertEqual(
                    from_bits,
                    strategy.winning_columns(grid, piece),
                    render(grid),
                )

    def test_a_line_does_not_wrap_around_the_edge(self):
        """Tres fichas al final de una fila no se enganchan con la de al lado
        de la fila siguiente."""
        grid = strategy.parse_board(
            board(*['.......'] * 4, 'A......', '....AAA')
        )
        position, mask, geo = strategy._to_bitboards(grid, 'A')
        spots = strategy._winning_spots(position, mask, geo)
        playable = (mask + geo.bottom) & geo.board

        self.assertEqual(spots & playable, playable & geo.column[3])


class TestForcedLines(unittest.TestCase):
    def test_builds_the_double_threat(self):
        """Con ..AA.. la unica jugada que gana a la fuerza es la col 4: deja
        AAA con las dos puntas libres y el rival solo puede tapar una."""
        self.assertEqual(
            strategy.choose_column(
                board(*['.......'] * 5, 'B.AA..B'), 'A', **FAST),
            4,
        )

    def test_a_lost_position_still_returns_a_legal_column(self):
        """El rival tiene dos amenazas jugables: se pierda como se pierda, hay
        que devolver una columna valida."""
        lost = board(*['.......'] * 5, '.BBB...')
        grid = strategy.parse_board(lost)

        self.assertIn(
            strategy.choose_column(lost, 'A', **FAST),
            strategy.valid_columns(grid),
        )

    def test_finds_the_win_before_running_out_of_depth(self):
        """El mate esta a 5 plies; con profundidad 3 no se llega, pero las
        podas exactas lo detectan igual."""
        grid = strategy.parse_board(board(*['.......'] * 5, 'B.AA..B'))

        self.assertEqual(strategy.best_column(grid, 'A', max_depth=3), 4)


class TestOtherBoardSizes(unittest.TestCase):
    def test_plays_on_a_square_board(self):
        small = board(*['.....'] * 5)

        self.assertIn(strategy.choose_column(small, 'A', **FAST), range(5))

    def test_plays_on_a_wider_board(self):
        wide = board(*['.' * 9] * 7)

        self.assertIn(strategy.choose_column(wide, 'A', **FAST), range(9))


class TestNeverLoses(unittest.TestCase):
    def test_does_not_lose_to_a_greedy_opponent(self):
        """Rival tipico de torneo: gana si puede, tapa si tiene que tapar, y
        si no juega lo mas al centro posible."""
        def greedy(grid, me, rival):
            for piece in (me, rival):
                wins = strategy.winning_columns(grid, piece)
                if wins:
                    return wins[0]
            return strategy._ordered_columns(
                strategy.valid_columns(grid), len(grid[0]))[0]

        for engine_starts in (True, False):
            grid = strategy.parse_board(EMPTY_BOARD)
            for turn in range(42):
                columns = strategy.valid_columns(grid)
                if not columns:
                    break
                engine_turn = (turn % 2 == 0) == engine_starts
                piece = 'A' if engine_turn else 'B'
                if engine_turn:
                    col = strategy.choose_column(render(grid), 'A', **FAST)
                else:
                    col = greedy(grid, 'B', 'A')
                self.assertIn(col, columns)
                row = strategy._landing_row(grid, col)
                grid[row][col] = piece
                if strategy._is_win(grid, row, col, piece):
                    self.assertEqual(
                        piece, 'A',
                        'perdio contra el rival goloso abriendo={}'.format(
                            engine_starts),
                    )
                    break


class TestResolvePiece(unittest.TestCase):
    def test_trusts_the_server_when_the_piece_is_on_the_board(self):
        grid = strategy.parse_board(board(*['.......'] * 5, 'AB.....'))

        self.assertEqual(strategy.resolve_piece(grid, 'B'), 'B')

    def test_an_empty_board_leaves_the_piece_as_is(self):
        grid = strategy.parse_board(EMPTY_BOARD)

        self.assertEqual(strategy.resolve_piece(grid, 'X'), 'X')

    def test_our_first_move_leaves_the_piece_as_is(self):
        """Solo jugo el rival: que nuestra ficha no este es lo normal."""
        grid = strategy.parse_board(board(*['.......'] * 5, '...B...'))

        self.assertEqual(strategy.resolve_piece(grid, 'A'), 'A')

    def test_a_side_that_matches_nothing_is_deduced_by_counting(self):
        """Si el server dice 'red' y el tablero viene con X y O, la nuestra es
        la que tiene menos fichas: es la que tiene que mover."""
        grid = strategy.parse_board(
            board('.......', '.......', '.......', '.......', '...X...',
                  '..XOX..')
        )

        self.assertEqual(strategy.resolve_piece(grid, 'r'), 'O')

    def test_the_deduced_piece_is_the_one_the_engine_plays(self):
        """Con X a punto de hacer 4 en fila, jugamos como O y hay que tapar."""
        mismatched = board(*['.......'] * 5, 'XXX.OO.')

        self.assertEqual(strategy.choose_column(mismatched, 'rojo', **FAST), 3)


def solve(state, me, rival, memo):
    """Valor exacto de la posicion para el que mueve: +1 gana, 0 empata, -1
    pierde. Sin heuristica y sin limite de profundidad, o sea la verdad."""
    cached = memo.get((state, me))
    if cached is not None:
        return cached

    grid = [list(row) for row in state]
    best = None
    for col in strategy.valid_columns(grid):
        row = strategy._landing_row(grid, col)
        grid[row][col] = me
        if strategy._is_win(grid, row, col, me):
            value = 1
        else:
            value = -solve(
                tuple(''.join(r) for r in grid), rival, me, memo)
        grid[row][col] = strategy.EMPTY
        if best is None or value > best:
            best = value
        if best == 1:
            break

    best = 0 if best is None else best
    memo[(state, me)] = best
    return best


class TestPlaysPerfectlyOnASmallBoard(unittest.TestCase):
    """En un tablero de 4x4 el motor llega hasta el final de la partida, asi
    que se le puede exigir juego perfecto: se compara contra un solucionador
    exacto por fuerza bruta."""

    def exact_values(self, grid, me, rival, memo):
        values = {}
        for col in strategy.valid_columns(grid):
            row = strategy._landing_row(grid, col)
            grid[row][col] = me
            if strategy._is_win(grid, row, col, me):
                values[col] = 1
            else:
                values[col] = -solve(
                    tuple(''.join(r) for r in grid), rival, me, memo)
            grid[row][col] = strategy.EMPTY
        return values

    # Presupuesto amplio a proposito: aca no se mide velocidad sino si la
    # jugada es la correcta, y el motor corta solo cuando termina de resolver
    # el tablero (no gasta el presupuesto entero).
    SOLVE = {'time_budget': 5}

    def test_never_picks_a_move_that_throws_the_game_away(self):
        rng = random.Random(20260825)
        memo = {}
        checked = 0

        for _ in range(24):
            grid = [[strategy.EMPTY] * 4 for _ in range(4)]
            piece = 'A'
            for _ in range(rng.randint(3, 9)):
                columns = strategy.valid_columns(grid)
                if not columns:
                    break
                col = rng.choice(columns)
                row = strategy._landing_row(grid, col)
                grid[row][col] = piece
                if strategy._is_win(grid, row, col, piece):
                    grid[row][col] = strategy.EMPTY
                    break
                piece = 'B' if piece == 'A' else 'A'

            if not strategy.valid_columns(grid):
                continue

            rival = 'B' if piece == 'A' else 'A'
            values = self.exact_values(grid, piece, rival, memo)
            chosen = strategy.choose_column(render(grid), piece, **self.SOLVE)
            checked += 1

            self.assertEqual(
                values[chosen], max(values.values()),
                'jugando {} eligio la columna {}; valores exactos {} en\n{}'
                .format(piece, chosen, values, render(grid)),
            )

        self.assertGreater(checked, 18, 'casi no se probaron posiciones')


if __name__ == '__main__':
    unittest.main()
