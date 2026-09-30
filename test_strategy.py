import unittest

import strategy
from strategy import BoardError


# Presupuesto chico para que los tests anden rapido; los casos estan armados
# para que la jugada correcta se vea a pocas jugadas.
FAST = 0.3


def board(*rows):
    return '\n'.join('|' + row + '|' for row in rows)


def turn(rows, side='A', remaining=200, score_1=0, score_2=0, mult_1=1, mult_2=1):
    return {
        'board': board(*rows),
        'rows': len(rows),
        'cols': len(rows[0]),
        'board_size': '{}x{}'.format(len(rows), len(rows[0])),
        'remaining_moves': remaining,
        'side': side,
        'score_1': score_1,
        'score_2': score_2,
        'multiplier_1': mult_1,
        'multiplier_2': mult_2,
    }


def choose(rows, **kwargs):
    return strategy.choose_direction(turn(rows, **kwargs), time_budget=FAST)


def state(rows, **kwargs):
    return strategy.build_state(turn(rows, **kwargs))


class TestParseBoard(unittest.TestCase):
    def test_strips_the_side_pipes_and_keeps_spaces(self):
        grid = strategy.parse_board('|  A |\n|a  1|')

        self.assertEqual(grid, ['  A ', 'a  1'])

    def test_pads_short_rows_to_the_declared_width(self):
        self.assertEqual(strategy.parse_board('|A|\n| |', cols=3), ['A  ', '   '])

    def test_skips_blank_lines_and_borders(self):
        grid = strategy.parse_board('+--+\n|A |\n| 1|\n+--+\n')

        self.assertEqual(grid, ['A ', ' 1'])

    def test_rows_glued_with_pipes_on_one_line(self):
        self.assertEqual(strategy.parse_board('|A || 1|'), ['A ', ' 1'])

    def test_carriage_returns_are_ignored(self):
        self.assertEqual(strategy.parse_board('|A |\r\n| 1|\r\n'), ['A ', ' 1'])

    def test_empty_board_is_an_error(self):
        for text in ('', None, '\n\n'):
            with self.assertRaises(BoardError):
                strategy.parse_board(text)

    def test_board_without_columns_is_an_error(self):
        with self.assertRaises(BoardError):
            strategy.parse_board('||\n||')


class TestTargetDigit(unittest.TestCase):
    def test_at_the_start_it_is_the_one(self):
        self.assertEqual(strategy.target_digit({1, 2, 3, 4, 5}), 1)

    def test_it_is_not_the_smallest_once_the_window_wraps(self):
        """El ejemplo del reglamento: con 1 6 7 8 9 toca el 6, no el 1."""
        self.assertEqual(strategy.target_digit({1, 6, 7, 8, 9}), 6)

    def test_other_wrapped_windows(self):
        self.assertEqual(strategy.target_digit({8, 9, 1, 2, 3}), 8)
        self.assertEqual(strategy.target_digit({9, 1, 2, 3, 4}), 9)

    def test_no_digits_no_target(self):
        self.assertIsNone(strategy.target_digit(set()))

    def test_all_nine_digits_has_no_start(self):
        self.assertIsNone(strategy.target_digit(range(1, 10)))

    def test_with_a_gap_the_longest_run_wins(self):
        self.assertEqual(strategy.target_digit({2, 3, 4, 7}), 2)

    def test_the_sequence_wraps_without_a_zero(self):
        self.assertEqual(strategy.next_digit(9), 1)
        self.assertEqual(strategy.next_digit(4), 5)
        self.assertEqual(strategy.previous_digit(1), 9)
        self.assertEqual(strategy.previous_digit(5), 4)


class TestTraceBody(unittest.TestCase):
    def test_straight_body_goes_from_tail_to_head(self):
        s = state(['aaaA ', '     ', ' B   '])

        self.assertEqual(s.bodies[0], (0, 1, 2, 3))

    def test_coiled_body_is_followed_segment_by_segment(self):
        #  aaa
        #  a a
        #  aA
        s = state(['aaa  ', 'a a  ', 'aA   ', '    B'])

        cols = 5
        cells = [divmod(c, cols) for c in s.bodies[0]]
        self.assertEqual(cells[-1], (2, 1))
        self.assertEqual(len(cells), 7)
        for (r1, c1), (r2, c2) in zip(cells, cells[1:]):
            self.assertEqual(abs(r1 - r2) + abs(c1 - c2), 1)

    def test_when_it_gives_up_it_still_returns_every_cell(self):
        neigh = strategy.neighbors(3, 3)

        body = strategy.trace_body(4, {0, 1, 2, 3, 5, 6, 7, 8}, neigh, limit=1)

        self.assertEqual(body[-1], 4)
        self.assertEqual(sorted(body), list(range(9)))

    def test_a_lone_head(self):
        s = state([' A ', '   ', ' B '])

        self.assertEqual(s.bodies, [(1,), (7,)])


class TestBuildState(unittest.TestCase):
    ROWS = ['aA 1 ', '  X #', ' 2 bB', '*    ']

    def test_reads_everything_off_the_board(self):
        s = state(self.ROWS)

        self.assertEqual((s.rows, s.cols), (4, 5))
        self.assertEqual(s.digits, {1: (3,), 2: (11,)})
        self.assertEqual(s.target, 1)
        self.assertEqual(s.items, {7: 'X', 15: '*'})
        self.assertEqual(s.grid[9], strategy.WALL)
        self.assertEqual(s.bodies, [(0, 1), (13, 14)])

    def test_side_b_is_player_zero_with_its_own_score_and_multiplier(self):
        s = state(self.ROWS, side='B', score_1=10, score_2=20, mult_1=3, mult_2=2)

        self.assertEqual(s.bodies[0], (13, 14))
        self.assertEqual(s.scores, [20, 10])
        self.assertEqual(s.mults, [2, 3])

    def test_missing_fields_get_defaults(self):
        s = strategy.build_state({'board': board(*self.ROWS)})

        self.assertEqual(s.scores, [0, 0])
        self.assertEqual(s.mults, [1, 1])
        self.assertEqual(s.plies_left, strategy.DEFAULT_REMAINING_MOVES)

    def test_every_copy_of_a_digit_is_kept(self):
        s = state(['aA1 2', '1   1', '2  bB'])

        self.assertEqual(s.digits, {1: (2, 5, 9), 2: (4, 10)})
        self.assertEqual(s.target, 1)

    def test_unknown_side_is_taken_as_a(self):
        self.assertEqual(state(self.ROWS, side='?').bodies[0], (0, 1))

    def test_unknown_symbols_are_avoided_like_walls(self):
        s = state(['A?', ' B'])

        self.assertEqual(s.grid[1], strategy.WALL)

    def test_dots_are_empty(self):
        self.assertEqual(state(['A.', '.B']).grid[1], strategy.EMPTY)

    def test_without_my_head_there_is_no_state(self):
        self.assertIsNone(state(['  ', ' B']))

    def test_the_opponent_may_be_missing(self):
        self.assertEqual(state(['A ', '  ']).bodies[1], ())


class TestStep(unittest.TestCase):
    def test_a_plain_move_scores_one_and_drags_the_tail(self):
        s = state(['aA   ', '     ', '    B'])

        t = strategy.step(s, 0, 'right')

        self.assertEqual(t.bodies[0], (1, 2))
        self.assertEqual(t.scores[0], 1)
        self.assertEqual(t.grid[0], strategy.EMPTY)
        self.assertEqual(t.to_move, 1)
        self.assertEqual(t.plies_left, s.plies_left - 1)
        self.assertEqual(s.bodies[0], (0, 1))  # el original no cambia

    def test_the_right_digit_scores_times_the_multiplier_and_grows(self):
        s = state(['aA3  ', '    4', '5 6 7', '    B'], mult_1=2)

        t = strategy.step(s, 0, 'right')

        self.assertEqual(t.scores[0], 1 + 3 * 100 * 2)
        self.assertEqual(t.bodies[0], (0, 1, 2))
        self.assertEqual(t.target, 4)
        self.assertNotIn(3, t.digits)
        self.assertIn(3, s.digits)

    def test_the_wrong_digit_costs_500_and_stays_in_the_sequence(self):
        s = state(['aA4  ', '    3', '     ', '    B'])

        t = strategy.step(s, 0, 'right')

        self.assertEqual(t.scores[0], 1 - 500)
        self.assertEqual(t.bodies[0], (1, 2))
        self.assertEqual(t.target, 3)
        self.assertIn(4, t.digits)

    def test_eating_the_last_known_digit_leaves_no_target(self):
        t = strategy.step(state(['aA1  ', '    B']), 0, 'right')

        self.assertIsNone(t.target)

    def test_x_bumps_the_multiplier_without_growing(self):
        s = state(['aAX  ', '    B'])

        t = strategy.step(s, 0, 'right')

        self.assertEqual(t.scores[0], 1 + 50)
        self.assertEqual(t.mults[0], 2)
        self.assertEqual(t.bodies[0], (1, 2))
        self.assertEqual(t.items, {})
        self.assertEqual(s.items, {2: 'X'})

    def test_old_star_food_scores_100_and_grows(self):
        t = strategy.step(state(['aA*  ', '    B'], mult_1=3), 0, 'right')

        self.assertEqual(t.scores[0], 1 + 300)
        self.assertEqual(len(t.bodies[0]), 3)

    def test_hitting_the_wall_costs_500_and_the_snake_stays(self):
        s = state(['aA#  ', '    B'])

        t = strategy.step(s, 0, 'right')

        self.assertEqual(t.scores[0], -500)
        self.assertEqual(t.bodies[0], s.bodies[0])
        self.assertIsNone(t.crashed)

    def test_leaving_the_board_is_a_crash(self):
        self.assertEqual(strategy.step(state(['aA', ' B']), 0, 'right').crashed, 0)

    def test_running_into_a_body_is_a_crash(self):
        s = state(['aA ', ' b ', ' B '])

        self.assertEqual(strategy.step(s, 0, 'down').crashed, 0)
        self.assertEqual(strategy.step(s, 0, 'left').crashed, 0)

    def test_the_opponent_moves_too(self):
        s = state(['aA   ', '     ', '   bB'])

        t = strategy.step(s, 1, 'up')

        self.assertEqual(t.bodies[1], (14, 9))
        self.assertEqual(t.to_move, 0)

    def test_eating_one_copy_of_the_target_takes_them_all(self):
        s = state(['aA1 1', '  2  ', '1  2 ', '    B'])

        t = strategy.step(s, 0, 'right')

        self.assertEqual(t.scores[0], 1 + 100)
        self.assertEqual(len(t.bodies[0]), 3)
        self.assertNotIn(1, t.digits)
        self.assertEqual(t.target, 2)
        for cell in (4, 10):
            self.assertEqual(t.grid[cell], strategy.EMPTY)
        self.assertEqual(t.grid[2], strategy.SNAKE)
        self.assertEqual(s.digits[1], (2, 4, 10))  # el original no cambia

    def test_a_wrong_copy_only_uses_up_that_copy(self):
        s = state(['aA2 2', '  1  ', '2    ', '    B'])

        t = strategy.step(s, 0, 'right')

        self.assertEqual(t.scores[0], 1 - 500)
        self.assertEqual(t.digits[2], (4, 10))
        self.assertEqual(t.target, 1)
        self.assertEqual(len(t.bodies[0]), 2)

    def test_the_last_known_wrong_copy_stays_in_the_sequence(self):
        t = strategy.step(state(['aA2  ', '  1  ', '    B']), 0, 'right')

        self.assertEqual(t.digits[2], (2,))

    def test_a_missing_snake_just_passes(self):
        s = state(['aA ', '   '])

        t = strategy.step(s, 1, None)

        self.assertEqual(t.to_move, 0)
        self.assertEqual(t.plies_left, s.plies_left - 1)


class TestLegalMoves(unittest.TestCase):
    def test_crashes_are_left_out_but_the_wall_is_not(self):
        s = state(['aA#', ' b ', ' B '])

        self.assertEqual(strategy.legal_moves(s, 0), ['right'])

    def test_missing_snake_can_only_pass(self):
        self.assertEqual(strategy.legal_moves(state(['A ', '  ']), 1), [None])


class TestDistances(unittest.TestCase):
    def test_walls_block_and_digits_are_reached_but_not_crossed(self):
        s = state(['A#  ', ' 1  ', '    ', '   B'])

        dist, _ = strategy.distances(s, 0)

        self.assertEqual(dist[1], -1)    # el muro
        self.assertEqual(dist[5], 2)     # el 1
        self.assertEqual(dist[4], 1)

    def test_the_body_frees_up_from_the_tail(self):
        # La cabeza esta encerrada contra su propio cuerpo y el borde, pero
        # la cola se va a correr: el BFS la cuenta como salida.
        s = state(['aaa ', 'aAa ', '    ', '   B'])

        dist, area = strategy.distances(s, 0)

        self.assertGreater(area, 0)
        self.assertGreater(dist[5 + 4], 0)

    def test_a_missing_snake_reaches_nothing(self):
        dist, area = strategy.distances(state(['A ', '  ']), 1)

        self.assertEqual(area, 0)
        self.assertEqual(set(dist), {-1})


class TestEvaluate(unittest.TestCase):
    def test_being_closer_to_the_food_is_better(self):
        near = state(['   1', '  aA', '    ', 'B   '])
        far = state(['1   ', '  aA', '    ', 'B   '])

        self.assertGreater(strategy.evaluate(near), strategy.evaluate(far))

    def test_a_higher_multiplier_is_worth_something(self):
        rows = ['aA  ', '    ', '  bB']

        self.assertGreater(
            strategy.evaluate(state(rows, mult_1=2)),
            strategy.evaluate(state(rows)),
        )

    def test_being_boxed_in_is_terrible(self):
        free = state([' aA     ', '        ', '        ', 'B       '])
        boxed = state(['aA#     ', '###     ', '        ', 'B       '])

        self.assertLess(strategy.evaluate(boxed), strategy.evaluate(free) - 1000)

    def test_the_race_for_an_x_is_not_all_or_nothing(self):
        share = strategy._race_share

        self.assertIsNone(share(-1, -1, True))
        self.assertEqual(share(-1, 3, True), 0.0)
        self.assertEqual(share(3, -1, False), 1.0)
        self.assertGreater(share(3, 3, True), 0.5)
        self.assertLess(share(3, 3, False), 0.5)
        self.assertGreater(share(2, 8, False), 0.95)
        self.assertLess(share(3, 4, False), share(3, 5, False))

    def test_final_score_is_a_win_a_loss_or_a_draw(self):
        s = state(['A ', ' B'])
        s.scores = [10, 5]
        self.assertGreater(strategy.final_score(s), strategy.WIN)
        s.scores = [5, 10]
        self.assertLess(strategy.final_score(s), -strategy.WIN + 100)
        s.scores = [5, 5]
        self.assertEqual(strategy.final_score(s), 0)


class TestChooseDirection(unittest.TestCase):
    def test_eats_the_digit_that_is_next(self):
        rows = [
            '        ',
            '  aaA1  ',
            '        ',
            '    2   ',
            '  3     ',
            '     4  ',
            ' 5      ',
            '      bB',
        ]

        self.assertEqual(choose(rows), 'right')

    def test_does_not_take_the_smallest_digit_when_the_window_wrapped(self):
        """Con 1 6 7 8 9 toca el 6: el 1 que esta al lado es -500."""
        rows = [
            '        ',
            '  aaA1  ',
            '    6   ',
            '        ',
            ' 7      ',
            '     8  ',
            ' 9      ',
            '      bB',
        ]

        self.assertEqual(choose(rows), 'down')

    def test_goes_around_a_wrong_digit(self):
        rows = [
            '         ',
            '  aaA3 1 ',
            '         ',
            '         ',
            ' 2   4   ',
            '         ',
            '   5     ',
            '       bB',
        ]

        self.assertIn(choose(rows), ('up', 'down'))

    def test_never_leaves_the_board(self):
        rows = [
            'aaaA',
            '    ',
            '    ',
            'B   ',
        ]

        self.assertEqual(choose(rows), 'down')

    def test_does_not_run_into_the_wall(self):
        rows = [
            '     ',
            'aaA# ',
            '     ',
            '     ',
            '    B',
        ]

        self.assertIn(choose(rows), ('up', 'down'))

    def test_bumping_the_wall_beats_crashing(self):
        # Arriba el borde, abajo y atras el propio cuerpo: el muro es la
        # unica jugada que no pierde la partida.
        rows = [
            'aA#  ',
            'aa   ',
            '     ',
            '    B',
        ]

        self.assertEqual(choose(rows), 'right')

    def test_does_not_walk_into_a_dead_end(self):
        # A la derecha hay un bolsillo de dos celdas: entrar es chocar.
        rows = [
            '      ###',
            'aaaaaA  #',
            '      ###',
            '         ',
            '        B',
        ]

        self.assertIn(choose(rows), ('up', 'down'))

    def test_plays_side_b_too(self):
        rows = [
            'aA      ',
            '        ',
            '        ',
            '     bB1',
        ]

        self.assertEqual(choose(rows, side='B'), 'right')

    def test_grabs_a_nearby_multiplier_early(self):
        rows = [
            '         ',
            ' aaAX    ',
            '         ',
            '         ',
            '        1',
            '         ',
            '       bB',
        ]

        self.assertEqual(choose(rows, remaining=280), 'right')

    def test_traps_the_opponent_when_it_can(self):
        # B esta en un pasillo sin salida salvo por la celda de la derecha
        # de A; ocupandola, B choca en su proxima jugada.
        rows = [
            '######',
            'bbB  #',
            '####A#',
            '   aa ',
            '      ',
        ]

        self.assertEqual(choose(rows), 'up')

    def test_only_one_way_out(self):
        rows = [
            'aA ',
            'ab ',
            ' B ',
        ]

        self.assertEqual(choose(rows), 'right')

    def test_no_way_out_still_answers(self):
        rows = [
            'aAb',
            'aaB',
        ]

        self.assertIn(choose(rows), strategy.DIRECTIONS)

    def test_a_board_without_my_snake_gets_the_default(self):
        self.assertEqual(choose(['   ', ' B ']), strategy.DEFAULT_DIRECTION)

    def test_a_garbage_board_gets_the_default(self):
        data = {'board': '', 'side': 'A'}

        self.assertEqual(strategy.choose_direction(data), strategy.DEFAULT_DIRECTION)

    def test_without_time_it_still_returns_a_legal_move(self):
        s = state(['     ', ' aA  ', '     ', '    B'])

        move = strategy.best_direction(s, time_budget=0)

        self.assertIn(move, strategy.legal_moves(s, 0))

    def test_goes_for_the_nearest_copy_of_the_target(self):
        rows = [
            '         1',
            '          ',
            '  aaA     ',
            '          ',
            '    1     ',
            '          ',
            ' 2   3  4 ',
            '5     1 bB',
        ]

        self.assertEqual(choose(rows), 'down')

    def test_the_search_stops_at_the_end_of_the_game(self):
        # Queda una sola jugada: comer el 1 gana la partida por puntos.
        rows = [
            '        ',
            '  aaA1  ',
            '        ',
            '      bB',
        ]

        self.assertEqual(choose(rows, remaining=1, score_2=50), 'right')


if __name__ == '__main__':
    unittest.main()
