import random
import queue
from threading import Thread
from time import monotonic
from itertools import product, groupby

import arcade
import pyglet

from .networking import server, client
from . import __version__

N_ROWS_AND_COLS = 7
TEAMS = ["humans", "animals"]
COMPUTER_DELAY = 0.7

CARD_TYPES = {
    "fox": {
        "count": 6,
        "team": "animals",
        "points": 5,
        "eats": ["duck", "pheasant"],
    },
    "bear": {
        "count": 2,
        "team": "animals",
        "points": 10,
        "eats": ["hunter", "lumberjack"],
        "slow": True,
    },
    "duck": {
        "count": 7,
        "points": 2,
    },
    "pheasant": {
        "count": 8,
        "points": 3,
    },
    "hunter": {
        "count": 8,
        "team": "humans",
        "variants": ["up", "down", "left", "right"],
        "directional": True,
        "eats": ["duck", "pheasant", "fox", "bear"],
        "points": 5,
    },
    "lumberjack": {
        "count": 2,
        "team": "humans",
        "eats": ["tree"],
        "slow": True,
        "points": 5,
    },
    "tree": {
        "count": 15,
        "immovable": True,
        "variants": ["oak", "spruce"],
        "points": 2,
    },
}

MOVABLE_FOR = {}
for kind, data in CARD_TYPES.items():
    if data.get("immovable"):
        continue
    if team := data.get("team"):
        MOVABLE_FOR.setdefault(team, set()).add(kind)
    else:
        for team in TEAMS:
            MOVABLE_FOR.setdefault(team, set()).add(kind)


class InvalidMove(Exception):
    pass


class GameOver(Exception):
    pass


def generate_pile():
    result = []
    for kind, data in CARD_TYPES.items():
        for _ in range(data["count"]):
            if variants := data.get("variants"):
                result.append(f"{kind}_{random.choice(variants)}")
            else:
                result.append(kind)
    random.shuffle(result)
    return result


def can_see(point_1, point_2, allow_list, walls, max_distance=-1, check_resolution=2):
    distance = arcade.get_distance(point_1[0], point_1[1], point_2[0], point_2[1])
    steps = int(distance // check_resolution)
    for step in range(steps + 1):
        step_distance = step * check_resolution
        u = step_distance / distance
        midpoint = arcade.lerp_vec(point_1, point_2, u)
        if max_distance != -1 and step_distance > max_distance:
            return False
        sprite_list = arcade.get_sprites_at_point(midpoint, walls)
        for sprite in sprite_list:
            if sprite not in allow_list:
                return False
    return True


@type.__call__
class both:
    def __eq__(self, other):
        return other in ("animals", "humans")


class Halali:
    def __init__(self, deal=True):
        self.to_play = "animals"
        self.team = both
        self.cards = [[None] * N_ROWS_AND_COLS for _ in range(N_ROWS_AND_COLS)]
        card_pile = iter(generate_pile())
        if deal:
            for x in range(N_ROWS_AND_COLS):
                for y in range(N_ROWS_AND_COLS):
                    if x == y == (N_ROWS_AND_COLS//2):
                        continue
                    kind, _, variant = next(card_pile).partition("_")
                    card_type = CARD_TYPES[kind]
                    card = {
                        "kind": kind,
                        "facing": "down",
                    }
                    if variant:
                        card["variant"] = variant
                    if card_type.get("directional"):
                        card["directional"] = True
                    self.cards[x][y] = card

        self.points = {team: 0 for team in TEAMS}
        self.turns_left = None
        self._tiles_left = N_ROWS_AND_COLS * N_ROWS_AND_COLS - 1

    @property
    def can_play(self):
        return self.to_play == self.team

    def check_can_play(self, for_enemy=False):
        if for_enemy:
            if self.can_play:
                raise InvalidMove("Not other player's turn!")
        else:
            if not self.can_play:
                raise InvalidMove("Not your turn!")

    def validate_rescue(self, card_x, card_y, for_enemy=False):
        card = self.cards[card_x][card_y]
        if not card:
            raise InvalidMove("Trying to move empty tile")
        if CARD_TYPES[card["kind"]].get("team") != self.to_play:
            raise InvalidMove("Can't rescue neutral pieces")
        rescue_possibilities = [
            (0, N_ROWS_AND_COLS // 2, "y"),
            (N_ROWS_AND_COLS // 2, 0, "x"),
            (N_ROWS_AND_COLS - 1, N_ROWS_AND_COLS // 2, "y"),
            (N_ROWS_AND_COLS // 2, N_ROWS_AND_COLS - 1, "x"),
        ]
        for target_x, target_y, direction in rescue_possibilities:
            if (target_x, target_y) == (card_x, card_y):
                return True
            try:
                self.validate_move(
                    card_x,
                    card_y,
                    target_x,
                    target_y,
                    for_enemy=for_enemy,
                )
                if card_x == target_x and direction == "x":
                    return True
                elif card_y == target_y and direction == "y":
                    return True
                else:
                    continue  # direction mismatch
            except InvalidMove:
                continue
        raise InvalidMove("Can't escape from this place")

    def attempt_rescue(self, location, for_enemy=False):
        self.check_can_play(for_enemy=for_enemy)
        x, y = location
        card = self.cards[x][y]
        self.validate_rescue(x, y, for_enemy=for_enemy)
        self.cards[x][y] = None
        self.points[self.to_play] += CARD_TYPES[card["kind"]]["points"]
        self._swap_teams()
        return True

    def _swap_teams(self):
        if self.turns_left is not None:
            self.turns_left -= 0.5
        elif self._tiles_left == 0:
            self.turns_left = 5
        self.to_play = "animals" if self.to_play == "humans" else "humans"

    def attempt_reveal(self, location, for_enemy=False):
        self.check_can_play(for_enemy=for_enemy)
        x, y = location
        card = self.cards[x][y]
        self.validate_reveal(x, y, for_enemy=for_enemy)
        self._tiles_left -= 1
        card["facing"] = "up"
        self._swap_teams()
        return True

    def validate_reveal(self, card_x, card_y, for_enemy=False):
        card = self.cards[card_x][card_y]
        if not card:
            raise InvalidMove("Can't reveal empty spot")
        if card["facing"] == "up":
            raise InvalidMove("Can't reveal face-up card")
        return True

    def validate_move(self, card_x, card_y, target_x, target_y, for_enemy=False):
        if card_x == target_x and card_y == target_y:
            raise InvalidMove("Didn't move")
        if card_x != target_x and card_y != target_y:
            raise InvalidMove("Can't move diagonally")
        if for_enemy:
            team = {"humans": "animals", "animals": "humans"}[self.team]
        else:
            team = self.team

        moving = None
        if card_x != target_x:
            # moving horizontally
            smaller, bigger = min(card_x, target_x), max(card_x, target_x)
            for inbetween in range(smaller + 1, bigger):
                if self.cards[inbetween][card_y] is not None:
                    raise InvalidMove("Path obstructed")
            if card_x > target_x:
                moving = "left"
            else:
                moving = "right"
        elif card_y != target_y:
            # moving horizontally
            smaller, bigger = min(card_y, target_y), max(card_y, target_y)
            for inbetween in range(smaller + 1, bigger):
                if self.cards[card_x][inbetween] is not None:
                    raise InvalidMove("Path obstructed")
            if card_y > target_y:
                moving = "down"
            else:
                moving = "up"
        card = self.cards[card_x][card_y]
        if not card:
            raise InvalidMove("Can't move empty tile")
        if CARD_TYPES[card["kind"]].get("slow") and (bigger - smaller) > 1:
            raise InvalidMove(f"{card['kind']} can only move one tile")
        if CARD_TYPES[card["kind"]].get("immovable"):
            raise InvalidMove(f"{card['kind']} can't move")
        if card["kind"] not in MOVABLE_FOR[team]:
            raise InvalidMove(f"Team {team} can't move {card['kind']}")
        if card["facing"] != "up":
            raise InvalidMove("Can't move face-down card.")
        target = self.cards[target_x][target_y]
        if target:
            if target["facing"] != "up":
                raise InvalidMove("Can't go to face-down card.")
            if target["kind"] not in CARD_TYPES[card["kind"]].get("eats", []):
                raise InvalidMove(f"{card['kind']} can't eat {target['kind']}")
            if card.get("directional") and moving != card["variant"]:
                raise InvalidMove(f"{card['kind']} can only kill {card['variant']}")
        return True

    def attempt_move(self, card_loc, target_loc, for_enemy=False):
        self.check_can_play(for_enemy=for_enemy)
        card_x, card_y = card_loc
        target_x, target_y = target_loc
        self.validate_move(
            card_x,
            card_y,
            target_x,
            target_y,
            for_enemy=for_enemy,
        )
        if target := self.cards[target_x][target_y]:
            self.points[self.to_play] += CARD_TYPES[target["kind"]]["points"]
        self.cards[target_x][target_y] = self.cards[card_x][card_y]
        self.cards[card_x][card_y] = None
        self._swap_teams()
        return True

    def available_moves(self, location, for_enemy=False):
        x, y = location
        # horizontal:
        for target_x in range(N_ROWS_AND_COLS):
            try:
                self.validate_move(x, y, target_x, y, for_enemy=for_enemy)
                yield target_x, y
            except InvalidMove:
                pass
        # vertical:
        for target_y in range(N_ROWS_AND_COLS):
            try:
                self.validate_move(x, y, x, target_y, for_enemy=for_enemy)
                yield x, target_y
            except InvalidMove:
                pass

    def update(self, _view):
        if self.turns_left is not None and self.turns_left <= 0:
            raise GameOver


class NetworkedHalali(Halali):
    def attempt_move(self, card_loc, target_loc, for_enemy=False):
        super().attempt_move(card_loc, target_loc, for_enemy=for_enemy)
        if not for_enemy:
            self.send_queue.put(["move", card_loc, target_loc])
        return True

    def attempt_reveal(self, location, for_enemy=False):
        print("attempting reveal")
        super().attempt_reveal(location, for_enemy=for_enemy)
        print("success, communicating reveal")
        if not for_enemy:
            self.send_queue.put(["reveal", location])
        return True

    def attempt_rescue(self, location, for_enemy=False):
        super().attempt_rescue(location, for_enemy=for_enemy)
        if not for_enemy:
            self.send_queue.put(["rescue", location])
        return True


class SPHalali(Halali):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.team = random.choice(["animals", "humans"])
        if not self.can_play:
            pyglet.clock.schedule_once(self.move_for_opponent, COMPUTER_DELAY)

    def _swap_teams(self):
        super()._swap_teams()
        if not self.can_play:
            pyglet.clock.schedule_once(self.move_for_opponent, COMPUTER_DELAY)

    def move_for_opponent(self, _dt):
        possible_moves = []
        for source in product(range(N_ROWS_AND_COLS), repeat=2):
            source_x, source_y = source
            card = self.cards[source_x][source_y]
            if not card:
                continue
            if card["facing"] == "down":
                possible_moves.append(("reveal", source, 0))
            elif card["kind"] not in MOVABLE_FOR[
                {"animals": "humans", "humans": "animals"}[self.team]
            ]:
                continue
            else:
                for target in self.available_moves(source, for_enemy=True):
                    target_x, target_y = target
                    target_card = self.cards[target_x][target_y]
                    if target_card:
                        possible_moves.append(("move", source, target, 2))
                    else:
                        possible_moves.append(("move", source, target, 1))
                if self.turns_left is not None:
                    try:
                        self.validate_rescue(source_x, source_y, for_enemy=True)
                        possible_moves.append(("rescue", source, 3))
                    except InvalidMove:
                        pass
        if possible_moves:
            possible_moves.sort(key=lambda m: -m[-1])
            good_moves = list(next(groupby(possible_moves, lambda x: x[-1]))[1])
            random.shuffle(good_moves)
            move = good_moves[0]
            match move:
                case ["move", source, target, *_]:
                    try:
                        self.attempt_move(source, target, for_enemy=True)
                        self.view.move(source, target)
                    except InvalidMove as e:
                        print(f"Rejecting {target} to {target} because {e.args[0]}")
                case ["reveal", source, *_]:
                    try:
                        self.attempt_reveal(source, for_enemy=True)
                        self.view.reveal(source)
                    except InvalidMove as e:
                        print(f"Rejecting {source} because {e.args[0]}")
                case ["rescue", source, *_]:
                    try:
                        self.attempt_rescue(source, for_enemy=True)
                        self.view.rescue(source)
                    except InvalidMove as e:
                        print(f"Rejecting {source} because {e.args[0]}")
                case other:
                    print("Wat", other)
        else:
            print("Can't find move")


class MPServerHalali(NetworkedHalali):
    # server thread with queue
    def __init__(self):
        super().__init__()
        self.send_queue, self.recv_queue = queue.Queue(), queue.Queue()
        Thread(target=server, kwargs={
            "send": self.send_queue,
            "recv": self.recv_queue,
        }).start()
        self.team = random.choice(["animals", "humans"])

    def update(self, view):
        super().update(view)
        # respond to incoming requests, if any
        response = None
        try:
            message = self.recv_queue.get(block=False, timeout=0)
        except queue.Empty:
            return
        print("Qstat:", self.send_queue.qsize(), self.recv_queue.qsize())
        print("Got message:", message)
        match message:
            case ["status"]:
                response = [
                    "status",
                    {
                        "to_play": self.to_play,
                        "client_team": ("animals"if self.team == "humans"else "humans"),
                        "points": self.points,
                        "version": __version__,
                    },
                ]
            case ["disconnected"]:
                ...  # go to main window
            case ["ping"]:
                response = None
            case ["cards"]:
                response = ["cards", self.cards]
            case ["move", source, target]:
                try:
                    self.attempt_move(source, target, for_enemy=True)
                    view.move(source, target)
                except InvalidMove as e:
                    # TODO: say what has to be undone
                    response = ["FIXME", "wrong move", e.args[0]]
                else:
                    response = ["ok"]
            case ["reveal", location]:
                try:
                    self.attempt_reveal(location, for_enemy=True)
                    view.reveal(location)
                except InvalidMove as e:
                    # TODO: say what has to be undone
                    response = ["FIXME", "wrong reveal", e.args[0]]
                else:
                    response = ["ok"]
            case ["rescue", location]:
                try:
                    self.attempt_rescue(location, for_enemy=True)
                    view.rescue(location)
                except InvalidMove as e:
                    # TODO: say what has to be undone
                    response = ["FIXME", "wrong rescue", e.args[0]]
                else:
                    response = ["ok"]
            case other:
                print("Unknown message", other)
                raise RuntimeError
        print("Answering", response)
        self.send_queue.put(response)


class MPClientHalali(NetworkedHalali):
    def __init__(self):
        super().__init__(deal=False)
        self.send_queue, self.recv_queue = queue.Queue(), queue.Queue()
        Thread(target=client, kwargs={
            "send": self.send_queue,
            "recv": self.recv_queue,
        }).start()
        self.send_queue.put(["status"])
        self.send_queue.put(["cards"])
        self.handle_response(None, block=True)
        self.handle_response(None, block=True)
        self.send_queue
        self.last_update = monotonic()
        self.update()

    def update(self, view=None):
        super().update(view)
        # make outgoing status requests every 0.5s
        t = monotonic()
        if t - self.last_update > 0.5:
            self.send_queue.put(["ping"])
            self.last_update = monotonic()
        self.handle_response(view)

    def handle_response(self, view, block=False):
        try:
            message = self.recv_queue.get(block=block)
        except queue.Empty:
            return
        print("Qstat:", self.send_queue.qsize(), self.recv_queue.qsize())
        match message:
            case ["status", status]:
                if __version__ != status["version"]:
                    raise RuntimeError("Version mismatch!")
                self.to_play = status["to_play"]
                self.team = status["client_team"]
                self.points = status["points"]
                self.turns_left = status.get("turns_left", None)
            case ["ok"]:
                pass
            case None:  # "pong"
                pass
            case ["disconnected"]:
                ...  # go to main window
            case ["cards", cards]:
                self.cards = cards
            case ["move", source, target]:
                try:
                    self.attempt_move(source, target, for_enemy=True)
                    view.move(source, target)
                except InvalidMove:
                    # TODO: handle desync. Fetch everything again?
                    pass
            case ["reveal", location]:
                try:
                    self.attempt_reveal(location, for_enemy=True)
                    view.reveal(location)
                except InvalidMove:
                    # TODO: handle desync. Fetch everything again?
                    pass
            case ["rescue", location]:
                try:
                    self.attempt_rescue(location, for_enemy=True)
                    view.rescue(location)
                except InvalidMove:
                    # TODO: handle desync. Fetch everything again?
                    pass
            case other:
                print("Unknown message", other)
                raise RuntimeError
