import asyncio
import json
import sys
import time
from random import randint

import websockets

SERVER_URI = "wss://server.codechallenge.net.ar/ws?token={}"

# A running text log of events received / actions sent per game, written to
# game_<game_id>.log when the match ends.
HISTORY = {}


def log_event(game_id, message):
    HISTORY.setdefault(game_id, []).append('< ' + json.dumps(message))


def log_action(game_id, message):
    HISTORY.setdefault(game_id, []).append('> ' + json.dumps(message))


def write_game_log(game_id):
    try:
        with open("game_{}.log".format(game_id), "w") as f:
            f.write("\n".join(HISTORY.get(game_id, [])) + "\n")
        print("saved game_{}.log".format(game_id))
    except OSError as e:
        print("could not write game log: {}".format(e))


async def send(websocket, action, data):
    message = json.dumps(
        {
            'action': action,
            'data': data,
        }
    )
    print(message)
    await websocket.send(message)


async def start(auth_token):
    uri = SERVER_URI.format(auth_token)
    while True:
        try:
            print('connection to {}'.format(uri))
            async with websockets.connect(uri) as websocket:
                print('connection READY!')
                await play(websocket)
        except KeyboardInterrupt:
            print('Exiting...')
            break
        except Exception:
            print('connection error!')
            time.sleep(3)


async def play(websocket):
    while True:
        try:
            request = await websocket.recv()
            print("< {}".format(request))
            request_data = json.loads(request)
            if request_data['event'] == 'update_user_list':
                pass
            if request_data['event'] == 'game_over':
                game_id = request_data['data'].get('game_id')
                if game_id:
                    log_event(game_id, request_data)
                    write_game_log(game_id)
            if request_data['event'] == 'challenge':
                await send(
                    websocket,
                    'accept_challenge',
                    {
                        'challenge_id': request_data['data']['challenge_id'],
                    },
                )
            if request_data['event'] == 'your_turn':
                log_event(request_data['data']['game_id'], request_data)
                await process_your_turn(websocket, request_data)
        except KeyboardInterrupt:
            print('Exiting...')
            break
        except Exception as e:
            print('error {}'.format(str(e)))
            break  # force login again


async def process_your_turn(websocket, request_data):
    await process_move(websocket, request_data)


async def process_move(websocket, request_data):
    board = request_data['data']['board']
    columns = board.find('|', 1) - 1
    print(board)
    move = {
        'game_id': request_data['data']['game_id'],
        'turn_token': request_data['data']['turn_token'],
        'col': randint(0, columns),
    }
    log_action(move['game_id'], {'action': 'move', 'data': move})
    await send(websocket, 'move', move)


async def process_wall(websocket, request_data):
    await send(
        websocket,
        'wall',
        {
            'game_id': request_data['data']['game_id'],
            'turn_token': request_data['data']['turn_token'],
            'row': randint(0, 8),
            'col': randint(0, 8),
            'orientation': 'h' if randint(0, 1) == 0 else 'v',
        },
    )


def main(argv):
    if len(argv) >= 2:
        asyncio.run(start(argv[1]))
        return 0
    print('please provide your auth_token')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
