import unittest

import strategy


def board(*rows):
    return '\n'.join(rows)


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


if __name__ == '__main__':
    unittest.main()
