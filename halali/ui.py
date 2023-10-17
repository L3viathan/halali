import sys
import os
from itertools import count
from functools import partial

import arcade
import arcade.gui
import pyglet
from pyglet.math import Vec2

from .game import (
    Halali,
    SPHalali,
    MPServerHalali,
    MPClientHalali,
    MOVABLE_FOR,
    InvalidMove,
    GameOver,
    N_ROWS_AND_COLS,
)
from .settings import Settings

SCREEN_MARGIN = 100

SCREEN_TITLE = "Halali!"
TEXT_MARGIN = 50
COLOR_ANIMALS = arcade.color.AZURE
COLOR_HUMANS = arcade.color.CARROT_ORANGE
COLOR_NEUTRAL = (170, 170, 110)
COLOR_TEXT = (220, 220, 220)
COLOR_INDICATOR = (138, 43, 226)
DEBUG_MARGIN_TOP = 20
DEBUG_MARGIN_LEFT = 10
DEBUG_DISTANCE = 15
DEBUG_FONT_SIZE = 10

# How big are the cards?
CARD_SIZE = 100
PLACE_SIZE = CARD_SIZE - 20

SCREEN_WIDTH = N_ROWS_AND_COLS * CARD_SIZE + 2 * SCREEN_MARGIN
SCREEN_HEIGHT = N_ROWS_AND_COLS * CARD_SIZE + 2 * SCREEN_MARGIN
BORDER_WIDTH = 15

# How big is the mat we'll place the card on?
MAT_PERCENT_OVERSIZE = 1.25
MAT_HEIGHT = int(CARD_SIZE * MAT_PERCENT_OVERSIZE)
MAT_WIDTH = int(CARD_SIZE * MAT_PERCENT_OVERSIZE)

# How much space do we leave as a gap between the mats?
# Done as a percent of the mat size.
VERTICAL_MARGIN_PERCENT = 0.10
HORIZONTAL_MARGIN_PERCENT = 0.10

# The Y of the bottom row (2 piles)
BOTTOM_Y = MAT_HEIGHT / 2 + MAT_HEIGHT * VERTICAL_MARGIN_PERCENT

# The X of where to start putting things on the left side
START_X = MAT_WIDTH / 2 + MAT_WIDTH * HORIZONTAL_MARGIN_PERCENT


def round_position(position):
    x, y = position
    nearest = CARD_SIZE // 2
    return (
        nearest * round(x / nearest),
        nearest * round(y / nearest),
    )

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
        int((x - SCREEN_MARGIN - CARD_SIZE / 2) / CARD_SIZE),
        int((y - SCREEN_MARGIN - CARD_SIZE / 2) / CARD_SIZE),
    )

def position_from_location(location):
    x, y = location
    return (
        SCREEN_MARGIN + CARD_SIZE / 2 + x * CARD_SIZE,
        SCREEN_MARGIN + CARD_SIZE / 2 + y * CARD_SIZE,
    )


class Then:
    def __init__(self, then):
        self.then = then


class Card(arcade.Sprite):
    def __init__(self, card_info):
        """ Card constructor """

        self.facing = "down"
        self.direction = None
        self._easings = []

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

    def __repr__(self):
        return f"<{self.kind} O:{self.orig_position} F:{self.facing}>"

    def animate(self, attribute, final_value=None, duration=0, delay=0, _delay=0, ease="linear"):
        # returns a partial of itself, with a delay set equal to the delay + duration
        delay = delay + _delay
        pyglet.clock.schedule_once(
            self.animate_now,
            delay,
            attribute=attribute,
            duration=duration,
            final_value=final_value,
            ease=ease,
        )
        return Then(partial(self.animate, _delay=delay + duration))

    def animate_now(self, _dt, attribute, final_value, duration, ease="linear"):
        # start easing, also schedule a simple setter at the end?
        if isinstance(attribute, str):
            if not final_value or not duration:
                raise ValueError("animate() missing final_value or duration")
            start_value = getattr(self, attribute)
            easing = arcade.ease_value(
                start_value,
                final_value,
                time=duration,
                ease_function=getattr(arcade, ease),
            )
            self._easings.append((attribute, easing))
        elif attribute is None:
            # this is such that you can do stuff like:
            # card.animate(...).then(target_card and target_card.kill)
            pass
        else:
            attribute()

    def on_update(self, delta_time):
        n_easings = len(self._easings)
        for i, (attr, easing) in enumerate(reversed(self._easings)):
            done, new_val = arcade.ease_update(easing, delta_time)
            if done:
                self._easings.pop(n_easings - i - 1)
                new_val = easing.end_value
            setattr(self, attr, new_val)

    @property
    def game_position(self):
        if self.being_held:
            return self.orig_position
        return self.position

    def hold(self):
        # sometimes non-integer positions can happen, probably when the update
        # fires concurrently with the mouse_move event. Therefore: rounding.
        self.animate("scale", 1.1, duration=0.1)
        self.orig_position = round_position(self.position)
        self.being_held = True

    def release(self):
        self.animate("scale", 1, duration=0.1)
        self.being_held = False
        self.orig_position = None

    def turn_over(self):
        self.facing = "up"
        self.set_texture(1)


class GameView(arcade.View):
    def __init__(self, mode, settings):
        super().__init__()

        self.held_card = None
        self.camera_game = arcade.Camera(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.camera_hud = arcade.Camera(SCREEN_WIDTH, SCREEN_HEIGHT)
        self.settings = settings
        self._exits_added = False
        self.debug = False
        self.debug_info = {
            "mode": mode,
        }
        match mode:
            case "hotseat":
                self.game = Halali()
            case "singleplayer":
                self.game = SPHalali(view=self)
            case "host":
                self.game = MPServerHalali()
            case "join":
                self.game = MPClientHalali()
            case other:
                raise RuntimeError(f"Unknown game mode {other}")

        if self.settings["music"]:
            self.bgmusic = arcade.play_sound(
                arcade.load_sound(path("resources/nature-walk-124997.wav")),
                looping=True,
            )
        else:
            self.bgmusic = None

        arcade.set_background_color(arcade.color.AMAZON)

        self.place_list = arcade.SpriteList()
        for x in range(N_ROWS_AND_COLS):
            for y in range(N_ROWS_AND_COLS):
                place = arcade.SpriteSolidColor(
                    PLACE_SIZE,
                    PLACE_SIZE,
                    arcade.csscolor.DARK_OLIVE_GREEN,
                )
                place.is_exit = False
                place.position = position_from_location((x, y))
                self.place_list.append(place)

        self.card_list = arcade.SpriteList()
        self.indicator_list = arcade.SpriteList()
        self.sync_cards()

        self.animal_score = arcade.Text(
            "0",
            start_x=TEXT_MARGIN,
            start_y=TEXT_MARGIN,
            anchor_x="center",
            anchor_y="center",
            font_size=36,
            color=COLOR_TEXT,
        )
        self.human_score = arcade.Text(
            "0",
            start_x=SCREEN_WIDTH - TEXT_MARGIN,
            start_y=TEXT_MARGIN,
            anchor_x="center",
            anchor_y="center",
            font_size=36,
            color=COLOR_TEXT,
        )
        self.turn_counter = arcade.Text(
            "5 turns left",
            start_x=SCREEN_WIDTH//2,
            start_y=SCREEN_HEIGHT - TEXT_MARGIN * 0.75,
            anchor_x="center",
            anchor_y="center",
            font_size=36,
            color=COLOR_TEXT,
        )

    def reveal(self, location_or_card):
        if isinstance(location_or_card, Card):
            cards = [location_or_card]
        else:
            position = position_from_location(location_or_card)
            cards = arcade.get_sprites_at_point(position, self.card_list)

        for card in cards:
            card.animate(
                "scale",
                1.25,
                duration=0.1,
            ).then(card.turn_over).then(
                "scale",
                1,
                duration=0.1,
            )

    def rescue(self, location_or_card):
        if isinstance(location_or_card, Card):
            cards = [location_or_card]
        else:
            position = position_from_location(location_or_card)
            cards = arcade.get_sprites_at_point(position, self.card_list)

        for card in cards:
            card.kill()

    def move(self, source_location_or_card, target_location):
        if isinstance(source_location_or_card, Card):
            source_cards = [source_location_or_card]
        else:
            source_position = position_from_location(source_location_or_card)
            source_cards = arcade.get_sprites_at_point(source_position, self.card_list)

        target_x, target_y = target_position = position_from_location(target_location)
        for card in arcade.get_sprites_at_point(target_position, self.card_list):
            if card not in source_cards:
                target_card = card
                break
        else:
            target_card = None

        for card in source_cards:
            # pull to top
            self.card_list.remove(card)
            self.card_list.append(card)
            card.animate("center_x", target_x, duration=0.2, ease="ease_out")
            card.animate("center_y", target_y, duration=0.2, ease="ease_out").then(target_card and target_card.kill)

    @property
    def accent_color(self):
        if self.game.can_play:
            if self.game.to_play == "animals":
                return COLOR_ANIMALS
            if self.game.to_play == "humans":
                return COLOR_HUMANS
        return COLOR_NEUTRAL

    def sync_cards(self):
        self.card_list.clear()
        for x, row in enumerate(self.game.cards):
            for y, card_info in enumerate(row):
                if not card_info:
                    continue
                card = Card(card_info)
                card.position = position_from_location((x, y))
                self.card_list.append(card)

    def on_key_press(self, key, modifiers):
        if key == arcade.key.F2:
            self.debug = not self.debug
        elif key == arcade.key.F5:
            print("Syncing..")
            self.sync_cards()
        elif key == arcade.key.F8:
            self.debug_info["breakpoint"] = True

    def add_exits(self):
        self._exits_added = True
        for pos in [
            (
                SCREEN_MARGIN + CARD_SIZE / 2 + (N_ROWS_AND_COLS // 2) * CARD_SIZE,
                SCREEN_MARGIN + CARD_SIZE / 2 + -1 * CARD_SIZE,
            ),
            (
                SCREEN_MARGIN + CARD_SIZE / 2 + (N_ROWS_AND_COLS // 2) * CARD_SIZE,
                SCREEN_MARGIN + CARD_SIZE / 2 + N_ROWS_AND_COLS * CARD_SIZE,
            ),
            (
                SCREEN_MARGIN + CARD_SIZE / 2 + -1 * CARD_SIZE,
                SCREEN_MARGIN + CARD_SIZE / 2 + (N_ROWS_AND_COLS // 2) * CARD_SIZE,
            ),
            (
                SCREEN_MARGIN + CARD_SIZE / 2 + N_ROWS_AND_COLS * CARD_SIZE,
                SCREEN_MARGIN + CARD_SIZE / 2 + (N_ROWS_AND_COLS // 2) * CARD_SIZE,
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
        if self.debug:
            self.draw_debug_info()

    def draw_debug_info(self):
        c = count()
        arcade.draw_text(
            f"M: {self.debug_info['mode']}",
            DEBUG_MARGIN_LEFT,
            SCREEN_HEIGHT - (DEBUG_MARGIN_TOP + next(c) * DEBUG_DISTANCE),
            COLOR_TEXT,
            DEBUG_FONT_SIZE,
            align="left",
        )
        arcade.draw_text(
            f"H: {self.held_card!r}",
            DEBUG_MARGIN_LEFT,
            SCREEN_HEIGHT - (DEBUG_MARGIN_TOP + next(c) * DEBUG_DISTANCE),
            COLOR_TEXT,
            DEBUG_FONT_SIZE,
            align="left",
        )
        if pos := self.debug_info.get("mouse_pos"):
            cards = list(arcade.get_sprites_at_point(pos, self.card_list))
            if cards:
                arcade.draw_text(
                    f"C: {cards[0]!r}",
                    DEBUG_MARGIN_LEFT,
                    SCREEN_HEIGHT - (DEBUG_MARGIN_TOP + next(c) * DEBUG_DISTANCE),
                    COLOR_TEXT,
                    DEBUG_FONT_SIZE,
                    align="left",
                )
        if self.debug_info.pop("breakpoint", None):
            breakpoint()
            ...


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
                self.reveal(card)
                return
            if card.kind not in MOVABLE_FOR[self.game.to_play]:
                return
            self.held_card = cards[-1]
            self.held_card.hold()
            self.card_list.remove(self.held_card)
            self.card_list.append(self.held_card)
            if self.settings["indicators"]:
                for x, y in self.game.available_moves(
                    location_from_position(card.position),
                ):
                    indicator = arcade.SpriteSolidColor(
                        CARD_SIZE // 8,
                        CARD_SIZE // 8,
                        COLOR_INDICATOR,
                    )
                    indicator.position = position_from_location((x, y))
                    self.indicator_list.append(indicator)

    def on_mouse_motion(self, x, y, dx, dy):
        if self.debug:
            self.debug_info["mouse_pos"] = x, y
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
                        self.rescue(self.held_card)
                        self.held_card = None
                        return

                if self.game.attempt_move(
                    location_from_position(self.held_card.game_position),
                    location,
                ):
                    self.move(self.held_card, location)

            except InvalidMove as e:
                print(e.args[0])
                self.camera_game.shake(Vec2(10, 0), speed=5)
                game_pos_x, game_pos_y = self.held_card.game_position
                self.held_card.animate("center_x", game_pos_x, duration=0.2)
                self.held_card.animate("center_y", game_pos_y, duration=0.2)
            finally:
                if self.held_card:
                    self.held_card.release()
                    self.held_card = None
                self.indicator_list.clear()

    def on_update(self, delta_time):
        self.card_list.on_update(delta_time)

    def update(self, delta_time):
        if self.game.turns_left is not None and not self._exits_added:
            self.add_exits()
        if not self.held_card:
            try:
                self.game.update(self)
            except GameOver:
                if self.bgmusic:
                    arcade.stop_sound(self.bgmusic)
                game_over_view = GameOverView(self.game.points)
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
        arcade.set_background_color(arcade.color.BLACK)
        self.heading = arcade.Text(
            "Game over",
            start_x=SCREEN_WIDTH // 2,
            start_y=SCREEN_HEIGHT - TEXT_MARGIN,
            anchor_x="center",
            anchor_y="center",
            font_size=48,
            color=COLOR_TEXT,
        )
        self.result = arcade.Text(
            f"{self.winner} won! ({self.points['humans']}:{self.points['animals']})",
            start_x=SCREEN_WIDTH // 2,
            start_y=TEXT_MARGIN,
            anchor_x="center",
            anchor_y="center",
            font_size=32,
            color=COLOR_TEXT,
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


def build_settings(structure):
    settings = {}
    for part in structure:
        label = part["label"].lower()
        match part["type"]:
            case "menu":
                settings[label] = build_settings(part["content"])
            case "play":
                continue
            case "bool":
                settings[label] = part["value"]
            case "choice":
                settings[label] = part["choices"][0]
            case other:
                raise RuntimeError(f"Unknown settings type {other}")
    return settings


class SetupView(arcade.View):
    def __init__(self):
        super().__init__()
        self.texture = arcade.load_texture(path("resources/gameover.png"))
        self.manager = arcade.gui.UIManager()
        self.manager.enable()
        self.settings = Settings()
        self.menu = [
            {"label": "Play", "play": "singleplayer"},
            {"label": "Multiplayer", "menu": [
                    {"label": "Hot-Seat", "play": "hotseat"},
                    {"label": "Host", "play": "host"},
                    {"label": "Join", "play": "join"},
                ],
            },
            {"label": "Settings", "menu": [
                    {"label": "Indicators", "setting": "indicators"},
                    {"label": "Sound", "setting": "sound"},
                    {"label": "Music", "setting": "music"},
                ],
            },
        ]

        self._stack = []
        self.show_menu()

    def show_menu(self):
        self.manager.clear()

        self.v_box = arcade.gui.UIBoxLayout()

        elements = self.menu
        for part in self._stack:
            elements = elements[part]["menu"]

        if self._stack:
            back_button = arcade.gui.UIFlatButton(text="Back", width=200)
            self.v_box.add(back_button.with_space_around(bottom=20))

            @back_button.event("on_click")
            def on_click_back(event):
                self._stack.pop()
                self.show_menu()

        for i, element in enumerate(elements):
            label = element["label"]
            button = arcade.gui.UIFlatButton(text=label, width=200)
            match element:
                case {"play": mode}:
                    def on_click(event, mode=mode):
                        self._stack = []
                        self.manager.disable()
                        game_view = GameView(mode, self.settings.dump())
                        self.window.show_view(game_view)
                case {"menu": _}:
                    def on_click(event, i=i):  # noqa
                        self._stack.append(i)
                        self.show_menu()
                case {"setting": name}:
                    button.text = f"{label}: {self.settings.label(name)}"
                    def on_click(event, button=button, name=name, label=label):  # noqa
                        self.settings.click(name)
                        button.text = f"{label}: {self.settings.label(name)}"
                    # could add more events here
                case other:
                    raise RuntimeError(f"Unknown element {other}")

            self.v_box.add(button.with_space_around(bottom=20))
            button.event("on_click")(on_click)

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
