import random
import sys
import os
import arcade
import arcade.gui
from pyglet.math import Vec2

SCREEN_MARGIN = 100

SCREEN_TITLE = "Halali!"
TEXT_MARGIN = 50
COLOR_ANIMALS = arcade.color.AZURE
COLOR_HUMANS = arcade.color.CARROT_ORANGE

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


class ResetPosition(Exception):
    pass


class GameOver(Exception):
    pass


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


class Halali:
    def __init__(self):
        self.can_play = True  # not fixed for multiplayer games
        self.to_play = "animals"
        self.cards = [[None] * N_COLS for _ in range(N_ROWS)]
        card_pile = iter(generate_pile())
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
        self.tiles_left = N_ROWS * N_COLS - 1

    def attempt_rescue(self, location):
        if not self.can_play:
            raise ResetPosition("Not your turn!")
        x, y = location
        card = self.cards[x][y]
        if not card:
            raise ResetPosition("Trying to move empty tile")
        if CARD_TYPES[card["kind"]].get("team") != self.to_play:
            raise ResetPosition("Can't rescue neutral pieces")
        self.points[self.to_play] += CARD_TYPES[card["kind"]]["points"]
        self._swap_teams()
        return True

    def _swap_teams(self):
        if self.turns_left is not None:
            if self.turns_left <= 0:
                raise GameOver
            self.turns_left -= 0.5
        elif self.tiles_left == 0:
            self.turns_left = 5
        self.to_play = "animals" if self.to_play == "humans" else "humans"

    def attempt_reveal(self, location):
        x, y = location
        card = self.cards[x][y]
        if not card:
            raise ResetPosition("Can't reveal empty spot")
        if card["facing"] == "up":
            raise ResetPosition("Can't reveal face-up card")
        self.tiles_left -= 1
        card["facing"] = "up"
        self._swap_teams()
        return True

    def validate_move(self, card_x, card_y, target_x, target_y):
        if card_x == target_x and card_y == target_y:
            raise ResetPosition("Didn't move")
        if card_x != target_x and card_y != target_y:
            raise ResetPosition("Can't move diagonally")
        moving = None
        if card_x != target_x:
            # moving horizontally
            smaller, bigger = min(card_x, target_x), max(card_x, target_x)
            for inbetween in range(smaller + 1, bigger):
                if self.cards[inbetween][card_y] is not None:
                    raise ResetPosition("Path obstructed")
            if card_x > target_x:
                moving = "left"
            else:
                moving = "right"
        elif card_y != target_y:
            # moving horizontally
            smaller, bigger = min(card_y, target_y), max(card_y, target_y)
            for inbetween in range(smaller + 1, bigger):
                if self.cards[card_x][inbetween] is not None:
                    raise ResetPosition("Path obstructed")
            if card_y > target_y:
                moving = "down"
            else:
                moving = "up"

        card = self.cards[card_x][card_y]
        target = self.cards[target_x][target_y]
        if target:
            if target["facing"] != "up":
                raise ResetPosition("Can't go to face-down card.")
            if target["kind"] not in CARD_TYPES[card["kind"]].get("eats", []):
                raise ResetPosition(f"{card['kind']} can't eat {target['kind']}")
            if card.get("directional") and moving != card["variant"]:
                raise ResetPosition(f"{card['kind']} can only kill {card['variant']}")
        return True

    def attempt_move(self, card_loc, target_loc):
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
            except ResetPosition:
                pass
        # vertical:
        for target_y in range(N_ROWS):
            try:
                self.validate_move(x, y, x, target_y)
                yield x, target_y
            except ResetPosition:
                pass


class MPServerHalali(Halali):
    # server thread with queue
    ...


class MPClientHalali:
    def __init__(self):
        self.conn = ...  # from settings? autodiscovery?


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
        self.turns_left = None
        self.camera_game = arcade.Camera(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.camera_hud = arcade.Camera(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.settings = settings

    @property
    def accent_color(self):
        if self.game.to_play == "animals":
            return COLOR_ANIMALS
        if self.game.to_play == "humans":
            return COLOR_HUMANS

    def setup(self):
        self.game = Halali()
        arcade.set_background_color(arcade.color.AMAZON)

        self.tiles_left = N_ROWS * N_COLS - 1
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
            if card.facing == "down" and self.game.attempt_reveal(
                location_from_position(card.position),
            ):
                card.turn_over()
                if self.game.turns_left == 5:
                    self.add_exits()
                return
            if card.kind not in MOVABLE_FOR[self.game.to_play]:
                return
            self.held_card = cards[-1]
            self.held_card.hold()
            self.card_list.remove(self.held_card)
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
                    raise ResetPosition("Not intersecting with a place")
                if self.held_card.game_position == place.position:
                    # Didn't move card
                    raise ResetPosition("Already at this place")

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

            except ResetPosition as e:
                print(e.args[0])
                self.camera_game.shake(Vec2(10, 0), speed=5)
                self.held_card.position = self.held_card.game_position
            except GameOver:
                game_over_view = GameOverView(self.game.points)
                game_over_view.setup()
                self.window.show_view(game_over_view)
            finally:
                if self.held_card:
                    self.card_list.append(self.held_card)
                    self.held_card.release()
                    self.held_card = None
                self.indicator_list.clear()


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
        game_view = GameView()
        game_view.setup()
        self.window.show_view(game_view)


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
