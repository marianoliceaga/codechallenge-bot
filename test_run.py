import asyncio
import json
import os
import tempfile
import unittest
from unittest import mock

import run


class FakeWebSocket:
    """Feeds canned messages to play() and records what the bot sends back."""

    def __init__(self, incoming=None):
        self.incoming = list(incoming or [])
        self.sent = []

    async def recv(self):
        if not self.incoming:
            raise ConnectionError('no more messages')
        return self.incoming.pop(0)

    async def send(self, message):
        self.sent.append(json.loads(message))

    @property
    def sent_actions(self):
        return [m['action'] for m in self.sent]


class HistoryTestCase(unittest.TestCase):
    """run.HISTORY is module level state, so every test starts from scratch."""

    def setUp(self):
        self._history = dict(run.HISTORY)
        run.HISTORY.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        run.HISTORY.clear()
        run.HISTORY.update(self._history)


class InTempDirTestCase(HistoryTestCase):
    """write_game_log() writes to the cwd, so tests run inside a temp dir."""

    def setUp(self):
        super().setUp()
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        cwd = os.getcwd()
        os.chdir(self.tmpdir.name)
        self.addCleanup(os.chdir, cwd)


EMPTY_BOARD = '\n'.join(['.......'] * 6)


def your_turn(game_id='g1', board=EMPTY_BOARD, turn_token='tok', side='A'):
    return json.dumps(
        {
            'event': 'your_turn',
            'data': {
                'game_id': game_id,
                'board': board,
                'turn_token': turn_token,
                'side': side,
            },
        }
    )


class TestLogging(HistoryTestCase):
    def test_events_are_marked_with_lt_and_actions_with_gt(self):
        run.log_event('g1', {'event': 'your_turn'})
        run.log_action('g1', {'action': 'move'})

        self.assertEqual(
            run.HISTORY['g1'],
            ['< {"event": "your_turn"}', '> {"action": "move"}'],
        )

    def test_history_is_kept_per_game(self):
        run.log_event('g1', {'event': 'a'})
        run.log_event('g2', {'event': 'b'})

        self.assertEqual(len(run.HISTORY['g1']), 1)
        self.assertEqual(len(run.HISTORY['g2']), 1)


class TestWriteGameLog(InTempDirTestCase):
    def test_writes_one_message_per_line(self):
        run.log_event('g1', {'event': 'your_turn'})
        run.log_action('g1', {'action': 'move'})

        run.write_game_log('g1')

        with open('game_g1.log') as f:
            lines = f.read().splitlines()
        self.assertEqual(
            lines, ['< {"event": "your_turn"}', '> {"action": "move"}']
        )

    def test_unknown_game_writes_an_empty_log(self):
        run.write_game_log('nope')

        with open('game_nope.log') as f:
            self.assertEqual(f.read(), '\n')

    def test_write_failure_is_swallowed(self):
        with mock.patch('builtins.open', side_effect=OSError('disk full')):
            run.write_game_log('g1')  # must not raise


class TestSend(unittest.TestCase):
    def test_wraps_payload_in_an_action_envelope(self):
        ws = FakeWebSocket()

        asyncio.run(run.send(ws, 'move', {'col': 3}))

        self.assertEqual(ws.sent, [{'action': 'move', 'data': {'col': 3}}])


class TestProcessMove(HistoryTestCase):
    def test_the_column_comes_from_the_strategy(self):
        ws = FakeWebSocket()
        request = json.loads(your_turn(side='A'))

        with mock.patch('run.strategy.choose_column', return_value=5) as pick:
            asyncio.run(run.process_move(ws, request))

        pick.assert_called_once_with(EMPTY_BOARD, 'A')
        self.assertEqual(ws.sent[0]['data']['col'], 5)

    def test_it_opens_in_the_center_for_real(self):
        """Sin mocks: el bot ya no juega al azar."""
        ws = FakeWebSocket()

        asyncio.run(run.process_move(ws, json.loads(your_turn())))

        self.assertEqual(ws.sent[0]['data']['col'], 3)

    def test_move_carries_the_turn_token(self):
        ws = FakeWebSocket()
        request = json.loads(your_turn(turn_token='abc123'))

        asyncio.run(run.process_move(ws, request))

        self.assertEqual(ws.sent[0]['data']['turn_token'], 'abc123')

    def test_move_is_recorded_in_the_history(self):
        ws = FakeWebSocket()

        asyncio.run(run.process_move(ws, json.loads(your_turn())))

        self.assertEqual(len(run.HISTORY['g1']), 1)
        self.assertTrue(run.HISTORY['g1'][0].startswith('> '))


class TestPlay(InTempDirTestCase):
    def test_challenges_are_accepted(self):
        challenge = json.dumps(
            {'event': 'challenge', 'data': {'challenge_id': 42}}
        )
        ws = FakeWebSocket([challenge])

        asyncio.run(run.play(ws))

        self.assertEqual(ws.sent_actions, ['accept_challenge'])
        self.assertEqual(ws.sent[0]['data'], {'challenge_id': 42})

    def test_your_turn_answers_with_a_move(self):
        ws = FakeWebSocket([your_turn()])

        asyncio.run(run.play(ws))

        self.assertEqual(ws.sent_actions, ['move'])

    def test_game_over_dumps_the_log_to_disk(self):
        game_over = json.dumps(
            {'event': 'game_over', 'data': {'game_id': 'g1'}}
        )
        ws = FakeWebSocket([your_turn(), game_over])

        asyncio.run(run.play(ws))

        self.assertTrue(os.path.exists('game_g1.log'))

    def test_game_over_without_game_id_writes_nothing(self):
        game_over = json.dumps({'event': 'game_over', 'data': {}})
        ws = FakeWebSocket([game_over])

        asyncio.run(run.play(ws))

        self.assertEqual(os.listdir('.'), [])

    def test_update_user_list_is_ignored(self):
        message = json.dumps({'event': 'update_user_list', 'data': {}})
        ws = FakeWebSocket([message])

        asyncio.run(run.play(ws))

        self.assertEqual(ws.sent, [])

    def test_malformed_json_stops_the_loop_instead_of_raising(self):
        ws = FakeWebSocket(['not json', your_turn()])

        asyncio.run(run.play(ws))

        self.assertEqual(ws.sent, [])


class TestPlayInterrupt(unittest.TestCase):
    def test_ctrl_c_stops_the_loop(self):
        ws = FakeWebSocket()
        ws.recv = mock.AsyncMock(side_effect=KeyboardInterrupt)

        asyncio.run(run.play(ws))  # must not raise

        self.assertEqual(ws.sent, [])


class FakeConnect:
    """Stands in for websockets.connect(uri) as an async context manager."""

    def __init__(self, websocket):
        self.websocket = websocket

    async def __aenter__(self):
        return self.websocket

    async def __aexit__(self, *exc_info):
        return False


class TestStart(unittest.TestCase):
    def test_connects_to_the_codechallenge_server_with_the_token(self):
        connect = mock.Mock(return_value=FakeConnect(FakeWebSocket()))

        with mock.patch('run.websockets.connect', connect), mock.patch(
            'run.play', mock.AsyncMock(side_effect=KeyboardInterrupt)
        ):
            asyncio.run(run.start('my-token'))

        connect.assert_called_once_with(
            'wss://server.codechallenge.net.ar/ws?token=my-token'
        )

    def test_reconnects_after_a_connection_error(self):
        connect = mock.Mock(
            side_effect=[OSError('boom'), KeyboardInterrupt]
        )
        sleep = mock.Mock()

        with mock.patch('run.websockets.connect', connect), mock.patch(
            'run.time.sleep', sleep
        ):
            asyncio.run(run.start('my-token'))

        self.assertEqual(connect.call_count, 2)
        sleep.assert_called_once_with(3)


class TestProcessWall(unittest.TestCase):
    def test_wall_orientation_is_h_or_v(self):
        ws = FakeWebSocket()
        request = {'data': {'game_id': 'g1', 'turn_token': 'tok'}}

        asyncio.run(run.process_wall(ws, request))

        self.assertEqual(ws.sent_actions, ['wall'])
        self.assertIn(ws.sent[0]['data']['orientation'], ('h', 'v'))


class TestMain(unittest.TestCase):
    def test_without_a_token_it_exits_with_an_error(self):
        self.assertEqual(run.main(['run.py']), 1)

    def test_with_a_token_it_starts_the_client(self):
        start = mock.Mock()
        with mock.patch('run.start', start), mock.patch('run.asyncio.run'):
            self.assertEqual(run.main(['run.py', 'my-token']), 0)

        start.assert_called_once_with('my-token')


class TestConfig(unittest.TestCase):
    def test_points_at_the_current_codechallenge_server(self):
        self.assertTrue(
            run.SERVER_URI.startswith('wss://server.codechallenge.net.ar/ws')
        )


if __name__ == '__main__':
    unittest.main()
