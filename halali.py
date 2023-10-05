import random
import sys
import json
import os
import socket
import queue
from threading import Thread
from time import sleep, monotonic
from contextlib import contextmanager
import arcade
import arcade.gui
from pyglet.math import Vec2
from zeroconf import (
    IPVersion,
    ServiceInfo,
    Zeroconf,
    ServiceBrowser,
    ServiceStateChange,
)

SCREEN_MARGIN = 100

SCREEN_TITLE = "Halali!"
TEXT_MARGIN = 50
COLOR_ANIMALS = arcade.color.AZURE
COLOR_HUMANS = arcade.color.CARROT_ORANGE
COLOR_NEUTRAL = (170, 170, 110)

# How big are the cards?
CARD_WIDTH = 100
CARD_HEIGHT = 100
N_ROWS = 7
N_COLS = 7

SCREEN_WIDTH = N_COLS * CARD_WIDTH + 2 * SCREEN_MARGIN
SCREEN_HEIGHT = N_ROWS * CARD_HEIGHT + 2 * SCREEN_MARGIN
BORDER_WIDTH = 15

# How big is the mat we'll place the card on?
MAT_PERCENT_OVERSIZE = 1.25
MAT_HEIGHT = int(CARD_HEIGHT * MAT_PERCENT_OVERSIZE)
MAT_WIDTH = int(CARD_WIDTH * MAT_PERCENT_OVERSIZE)

# How much space do we leave as a gap between the mats?
# Done as a percent of the mat size.
VERTICAL_MARGIN_PERCENT = 0.10
HORIZONTAL_MARGIN_PERCENT = 0.10

# The Y of the bottom row (2 piles)
BOTTOM_Y = MAT_HEIGHT / 2 + MAT_HEIGHT * VERTICAL_MARGIN_PERCENT

# The X of where to start putting things on the left side
START_X = MAT_WIDTH / 2 + MAT_WIDTH * HORIZONTAL_MARGIN_PERCENT

TEAMS = ["humans", "animals"]

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


@contextmanager
def advertise():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(0)
        try:
            s.connect(("10.254.254.254", 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = "127.0.0.1"
    info = ServiceInfo(
        "_halali._tcp.local.",
        f"{random.randint(1, 1000)}._halali._tcp.local.",
        addresses=[socket.inet_aton(IP)],
        port=58008,
    )
    zc = Zeroconf(ip_version=IPVersion.All)
    try:
        zc.register_service(info)
        yield
    finally:
        zc.unregister_service(info)
        zc.close()


def find_server():
    zc = Zeroconf(ip_version=IPVersion.All)
    server = None
    def handler(zeroconf, service_type, name, state_change):
        nonlocal server
        if state_change is ServiceStateChange.Added:
            if info := zeroconf.get_service_info(service_type, name):
                server = (
                    socket.inet_ntoa(info.addresses[0]),
                    info.port,
                )
                return

    ServiceBrowser(
        zc,
        ["_halali._tcp.local."],
        handlers=[handler],
    )
    try:
        for _ in range(20):
            if server:
                return server
            sleep(0.2)
    finally:
        zc.close()


def path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)


def location_from_position(position):
    x, y = position
    return (
        int((x - SCREEN_MARGIN - CARD_WIDTH / 2) / CARD_WIDTH),
        int((y - SCREEN_MARGIN - CARD_HEIGHT / 2) / CARD_HEIGHT),
    )

def position_from_location(location):
    x, y = location
    return (
        SCREEN_MARGIN + CARD_WIDTH / 2 + x * CARD_WIDTH,
        SCREEN_MARGIN + CARD_HEIGHT / 2 + y * CARD_HEIGHT,
    )



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


class Card(arcade.Sprite):
    def __init__(self, card_info):
        """ Card constructor """

        self.facing = "down"
        self.direction = None

        # Image to use for the sprite when face down
        self.image_file_name = path("resources/hidden.png")

        super().__init__(
            self.image_file_name,
            scale=1,
            hit_box_algorithm="None",
        )
        if "variant" in card_info:
            texture = f"{card_info['kind']}_{card_info['variant']}"
        else:
            texture = card_info["kind"]
        # drop texture variation in kinds
        self.append_texture(arcade.load_texture(path(f"resources/{texture}.png")))
        self.kind = card_info["kind"]
        self.being_held = False
        self.orig_position = None
        if card_info["facing"] == "up":
            self.turn_over()

    @property
    def game_position(self):
        if self.being_held:
            return self.orig_position
        return self.position

    def hold(self):
        self.orig_position = self.position
        self.being_held = True

    def release(self):
        self.being_held = False
        self.orig_position = None

    def turn_over(self):
        self.facing = "up"
        self.set_texture(1)


@type.__call__
class both:
    def __eq__(self, other):
        return other in ("animals", "humans")


class Halali:
    def __init__(self, deal=True):
        self.to_play = "animals"
        self.team = both
        self.cards = [[None] * N_COLS for _ in range(N_ROWS)]
        card_pile = iter(generate_pile())
        if deal:
            for x in range(N_COLS):
                for y in range(N_ROWS):
                    if x == y == (N_COLS//2):
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
        self._tiles_left = N_ROWS * N_COLS - 1

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

    def attempt_rescue(self, location, for_enemy=False):
        self.check_can_play(for_enemy=for_enemy)
        x, y = location
        card = self.cards[x][y]
        if not card:
            raise InvalidMove("Trying to move empty tile")
        if CARD_TYPES[card["kind"]].get("team") != self.to_play:
            raise InvalidMove("Can't rescue neutral pieces")
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
        if not card:
            raise InvalidMove("Can't reveal empty spot")
        if card["facing"] == "up":
            raise InvalidMove("Can't reveal face-up card")
        self._tiles_left -= 1
        card["facing"] = "up"
        self._swap_teams()
        return True

    def validate_move(self, card_x, card_y, target_x, target_y):
        if card_x == target_x and card_y == target_y:
            raise InvalidMove("Didn't move")
        if card_x != target_x and card_y != target_y:
            raise InvalidMove("Can't move diagonally")
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
        self.validate_move(card_x, card_y, target_x, target_y)
        if target := self.cards[target_x][target_y]:
            self.points[self.to_play] += CARD_TYPES[target["kind"]]["points"]
        self.cards[target_x][target_y] = self.cards[card_x][card_y]
        self.cards[card_x][card_y] = None
        self._swap_teams()
        return True

    def available_moves(self, location):
        x, y = location
        # horizontal:
        for target_x in range(N_COLS):
            try:
                self.validate_move(x, y, target_x, y)
                yield target_x, y
            except InvalidMove:
                pass
        # vertical:
        for target_y in range(N_ROWS):
            try:
                self.validate_move(x, y, x, target_y)
                yield x, target_y
            except InvalidMove:
                pass

    def update(self, _view):
        if self.turns_left is not None and self.turns_left <= 0:
            raise GameOver


def server(send, recv):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("", 58008))
        s.listen(1)
        print("Waiting for connection...")
        with advertise():
            conn, addr = s.accept()
        print(addr, "connected")
        while True:
            msg = conn.recv(8192)
            if not msg:
                recv.put(["disconnected"])
                return
            recv.put(json.loads(msg))  # TODO: make resilient
            while True:
                response = send.get()  # blocking, wait for game to respond
                if not response and send.qsize():
                    continue  # not guaranteed to work
                break
            print("Actually sending...")
            conn.sendall(json.dumps(response, separators=",:").encode())
    finally:
        s.close()


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

    # def _swap_teams(self):
    #     super()._swap_teams()
    #     if self._tiles_left == 0:
    #         self.turns_left = 5
    #     self.to_play = "animals" if self.to_play == "humans" else "humans"



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


def client(send, recv):
    conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    print("Connecting...")
    conn.connect(find_server())
    print("Connected!")
    while True:
        try:
            msg = send.get(block=False, timeout=0)
        except queue.Empty:
            sleep(0.5)
            continue
            # msg = {"T": "status"}
        conn.sendall(json.dumps(msg, separators=",:").encode())
        data = conn.recv(8192)
        if not data:
            return
        print("Received:", data)
        recv.put(json.loads(data))
        sleep(0.2)


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
                    # FIXME: also remove card
                except InvalidMove:
                    # TODO: handle desync. Fetch everything again?
                    pass
            case other:
                print("Unknown message", other)
                raise RuntimeError

    # to_play
    # turns_left
    # can_play
    # points
    # attempt_move()
    # attempt_rescue()
    # attempt_reveal()


class GameView(arcade.View):
    def __init__(self, settings):
        super().__init__()

        self.place_list = None
        self.card_list = None
        self.indicator_list = None
        self.held_card = None
        self.game = None
        self.animal_score = None
        self.human_score = None
        self.turn_counter = None
        self.camera_game = arcade.Camera(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.camera_hud = arcade.Camera(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.settings = settings
        self._exits_added = False

    def reveal(self, location):
        # used by multiplayer. also for singleplayer?
        position = position_from_location(location)
        for card in arcade.get_sprites_at_point(position, self.card_list):
            card.turn_over()

    def rescue(self, location):
        # used by multiplayer. also for singleplayer?
        position = position_from_location(location)
        for card in arcade.get_sprites_at_point(position, self.card_list):
            card.kill()

    def move(self, source, target):
        # used by multiplayer. also for singleplayer?
        target_position = position_from_location(target)
        for card in arcade.get_sprites_at_point(target_position, self.card_list):
            card.kill()
        source_position = position_from_location(source)
        for card in arcade.get_sprites_at_point(source_position, self.card_list):
            card.position = position_from_location(target)

    @property
    def accent_color(self):
        if self.game.can_play:
            if self.game.to_play == "animals":
                return COLOR_ANIMALS
            if self.game.to_play == "humans":
                return COLOR_HUMANS
        return COLOR_NEUTRAL

    def setup(self):
        if self.settings["mode"] == "Hot-Seat":
            self.game = Halali()
        elif self.settings["mode"] == "Host":
            self.game = MPServerHalali()
        elif self.settings["mode"] == "Join":
            self.game = MPClientHalali()
        arcade.set_background_color(arcade.color.AMAZON)

        self.place_list = arcade.SpriteList()
        for x in range(N_COLS):
            for y in range(N_ROWS):
                place = arcade.SpriteSolidColor(
                    CARD_WIDTH - 20,
                    CARD_HEIGHT - 20,
                    arcade.csscolor.DARK_OLIVE_GREEN,
                )
                place.is_exit = False
                place.position = position_from_location((x, y))
                self.place_list.append(place)

        self.card_list = arcade.SpriteList()
        self.indicator_list = arcade.SpriteList()
        self.sync_cards()

        self.held_card = None

        self.animal_score = arcade.Text(
            "0",
            start_x=TEXT_MARGIN,
            start_y=TEXT_MARGIN,
            anchor_x="center",
            anchor_y="center",
            font_size=36,
            color=(220, 220, 220),
        )
        self.human_score = arcade.Text(
            "0",
            start_x=SCREEN_WIDTH - TEXT_MARGIN,
            start_y=TEXT_MARGIN,
            anchor_x="center",
            anchor_y="center",
            font_size=36,
            color=(220, 220, 220),
        )
        self.turn_counter = arcade.Text(
            "5 turns left",
            start_x=SCREEN_WIDTH//2,
            start_y=SCREEN_HEIGHT - TEXT_MARGIN * 0.75,
            anchor_x="center",
            anchor_y="center",
            font_size=36,
            color=(220, 220, 220),
        )

    def sync_cards(self):
        self.card_list.clear()
        for x, row in enumerate(self.game.cards):
            for y, card_info in enumerate(row):
                if not card_info:
                    continue
                card = Card(card_info)
                card.position = position_from_location((x, y))
                self.card_list.append(card)

    def add_exits(self):
        self._exits_added = True
        for pos in [
            (
                SCREEN_MARGIN + CARD_WIDTH / 2 + (N_COLS // 2) * CARD_WIDTH,
                SCREEN_MARGIN + CARD_HEIGHT / 2 + -1 * CARD_HEIGHT,
            ),
            (
                SCREEN_MARGIN + CARD_WIDTH / 2 + (N_COLS // 2) * CARD_WIDTH,
                SCREEN_MARGIN + CARD_HEIGHT / 2 + N_ROWS * CARD_HEIGHT,
            ),
            (
                SCREEN_MARGIN + CARD_WIDTH / 2 + -1 * CARD_WIDTH,
                SCREEN_MARGIN + CARD_HEIGHT / 2 + (N_COLS // 2) * CARD_HEIGHT,
            ),
            (
                SCREEN_MARGIN + CARD_WIDTH / 2 + N_ROWS * CARD_WIDTH,
                SCREEN_MARGIN + CARD_HEIGHT / 2 + (N_COLS // 2) * CARD_HEIGHT,
            ),
        ]:
            exit = arcade.Sprite(
                path("resources/center.png"),
            )
            exit.is_exit = True
            exit.position = pos
            self.place_list.append(exit)

    def on_draw(self):
        """ Render the screen. """
        # Clear the screen
        self.clear()
        self.camera_game.use()
        self.place_list.draw()
        self.card_list.draw()
        if self.settings["indicators"]:
            self.indicator_list.draw()
        if self.held_card:
            self.held_card.draw()
        self.camera_hud.use()
        self.draw_hud()

    def draw_hud(self):
        arcade.draw_rectangle_outline(
            SCREEN_WIDTH // 2,
            SCREEN_HEIGHT // 2,
            SCREEN_WIDTH,
            SCREEN_HEIGHT,
            color=self.accent_color,
            border_width=BORDER_WIDTH,
        )

        arcade.draw_rectangle_filled(
            SCREEN_WIDTH,
            0,
            TEXT_MARGIN * 4,
            TEXT_MARGIN * 4,
            color=COLOR_HUMANS,
        )
        self.human_score.text = str(self.game.points["humans"])
        self.human_score.draw()

        arcade.draw_rectangle_filled(
            0,
            0,
            TEXT_MARGIN * 4,
            TEXT_MARGIN * 4,
            color=COLOR_ANIMALS,
        )
        self.animal_score.text = str(self.game.points["animals"])
        self.animal_score.draw()

        if self.game.turns_left is not None:
            x_pos = SCREEN_WIDTH // 8 * (1 if self.game.to_play == "animals" else 7)
            arcade.draw_rectangle_filled(
                x_pos,
                SCREEN_HEIGHT + TEXT_MARGIN // 2,
                SCREEN_WIDTH // 2,
                TEXT_MARGIN * 4,
                color=self.accent_color,
            )
            self.turn_counter.text = f"{round(self.game.turns_left + 0.1)} turns left"
            if self.game.to_play == "animals":
                self.turn_counter.x = TEXT_MARGIN
                self.turn_counter.anchor_x = "left"
            elif self.game.to_play == "humans":
                self.turn_counter.x = SCREEN_WIDTH - TEXT_MARGIN
                self.turn_counter.anchor_x = "right"
            self.turn_counter.draw()

    def on_mouse_press(self, x, y, button, key_modifiers):
        if not self.game.can_play:
            print("Can't play")
            return
        cards = arcade.get_sprites_at_point((x, y), self.card_list)
        if cards:
            card = cards[-1]
            loc = location_from_position(card.position)
            if card.facing == "down" and self.game.attempt_reveal(loc):
                card.turn_over()
                return
            if card.kind not in MOVABLE_FOR[self.game.to_play]:
                return
            self.held_card = cards[-1]
            self.held_card.hold()
            self.card_list.remove(self.held_card)
            if self.settings["indicators"]:
                for x, y in self.game.available_moves(
                    location_from_position(card.position),
                ):
                    indicator = arcade.SpriteSolidColor(
                        CARD_WIDTH // 8,
                        CARD_HEIGHT // 8,
                        (138, 43, 226),
                    )
                    indicator.position = position_from_location((x, y))
                    self.indicator_list.append(indicator)

    def on_mouse_motion(self, x, y, dx, dy):
        if self.held_card:
            self.held_card.center_x += dx
            self.held_card.center_y += dy

    def on_mouse_release(self, x, y, button, key_modifiers):
        if self.held_card:
            place, distance = arcade.get_closest_sprite(self.held_card, self.place_list)
            try:
                if not arcade.check_for_collision(self.held_card, place):
                    # Not on a place
                    raise InvalidMove("Not intersecting with a place")
                if self.held_card.game_position == place.position:
                    # Didn't move card
                    raise InvalidMove("Already at this place")

                location = location_from_position(place.position)
                if place.is_exit:
                    if self.game.attempt_rescue(
                        location_from_position(self.held_card.game_position),
                    ):
                        self.held_card.kill()
                        self.held_card = None
                        return

                if self.game.attempt_move(
                    location_from_position(self.held_card.game_position),
                    location,
                ):
                    other_cards = arcade.get_sprites_at_point(
                        place.position,
                        self.card_list,
                    )
                    for other_card in other_cards:
                        if other_card != self.held_card:
                            other_card.kill()
                    self.held_card.position = place.center_x, place.center_y

            except InvalidMove as e:
                print(e.args[0])
                self.camera_game.shake(Vec2(10, 0), speed=5)
                self.held_card.position = self.held_card.game_position
            finally:
                if self.held_card:
                    self.card_list.append(self.held_card)
                    self.held_card.release()
                    self.held_card = None
                self.indicator_list.clear()

    def update(self, delta_time):
        if self.game.turns_left is not None and not self._exits_added:
            self.add_exits()
        if not self.held_card:
            try:
                self.game.update(self)
            except GameOver:
                game_over_view = GameOverView(self.game.points)
                game_over_view.setup()
                self.window.show_view(game_over_view)


class GameOverView(arcade.View):
    def __init__(self, points):
        super().__init__()
        self.points = points
        self.texture = arcade.load_texture(path("resources/gameover.png"))
        self.winner = (
            "Animals"
            if self.points["animals"] > self.points["humans"]
            else "Humans"
        )

    def setup(self):
        arcade.set_background_color(arcade.color.BLACK)
        self.heading = arcade.Text(
            "Game over",
            start_x=SCREEN_WIDTH // 2,
            start_y=SCREEN_HEIGHT - TEXT_MARGIN,
            anchor_x="center",
            anchor_y="center",
            font_size=48,
            color=(220, 220, 220),
        )
        self.result = arcade.Text(
            f"{self.winner} won! ({self.points['humans']}:{self.points['animals']})",
            start_x=SCREEN_WIDTH // 2,
            start_y=TEXT_MARGIN,
            anchor_x="center",
            anchor_y="center",
            font_size=32,
            color=(220, 220, 220),
        )

    def on_draw(self):
        """ Draw this view """
        self.clear()
        self.texture.draw_sized(
            SCREEN_WIDTH / 2,
            SCREEN_HEIGHT / 2,
            SCREEN_WIDTH,
            SCREEN_HEIGHT * 0.75,
        )
        self.heading.draw()
        self.result.draw()

    def on_mouse_press(self, _x, _y, _button, _modifiers):
        """ If the user presses the mouse button, re-start the game. """
        self.window.show_view(SetupView())


class SetupView(arcade.View):
    def __init__(self):
        super().__init__()
        self.texture = arcade.load_texture(path("resources/gameover.png"))
        self.manager = arcade.gui.UIManager()
        self.manager.enable()
        self.settings = {
            "mode": "Hot-Seat",
            "indicators": False,
            "address": "",
        }


        self.v_box = arcade.gui.UIBoxLayout()

        start_button = arcade.gui.UIFlatButton(text="Start Game", width=200)
        self.v_box.add(start_button.with_space_around(bottom=20))

        @start_button.event("on_click")
        def on_click_start(event):
            self.manager.disable()
            game_view = GameView(self.settings)
            game_view.setup()
            self.window.show_view(game_view)

        mode_button = arcade.gui.UIFlatButton(text="Mode: Hot-Seat", width=200)
        self.v_box.add(mode_button.with_space_around(bottom=20))

        @mode_button.event("on_click")
        def on_click_mode(event):
            match self.settings["mode"]:
                case "Hot-Seat":
                    self.settings["mode"] = "Join"
                case "Join":
                    self.settings["mode"] = "Host"
                case "Host":
                    self.settings["mode"] = "Hot-Seat"
            mode_button.text = f"Mode: {self.settings['mode']}"

        indicators_button = arcade.gui.UIFlatButton(
            text="Indicators: off",
            width=200,
        )
        self.v_box.add(indicators_button.with_space_around(bottom=20))
        @indicators_button.event("on_click")
        def on_click_indicators(event):
            self.settings["indicators"] = not self.settings["indicators"]
            label = f"Indicators: {['off', 'on'][self.settings['indicators']]}"
            indicators_button.text = label

        self.manager.add(
            arcade.gui.UIAnchorWidget(
                anchor_x="center_x",
                anchor_y="center_y",
                child=self.v_box,
            )
        )

    def on_draw(self):
        self.clear()
        self.texture.draw_sized(
            SCREEN_WIDTH / 2,
            SCREEN_HEIGHT / 2,
            SCREEN_WIDTH,
            SCREEN_HEIGHT * 0.75,
        )
        self.manager.draw()


if __name__ == "__main__":
    window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)
    start_view = SetupView()
    window.show_view(start_view)
    arcade.run()
