import random
import arcade

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
        "variants": ["n", "w", "s", "e"],
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
    def __init__(self, kind):
        """ Card constructor """

        self.facing = "down"
        self.directional = False

        # Image to use for the sprite when face up
        self.image_file_name = ":resources:images/tiles/boxCrate.png"
        # background: topdown_tanks/tileGrass1.png

        # Call the parent
        super().__init__(
            self.image_file_name,
            scale=0.7,  # TODO
            # image_width=CARD_WIDTH,
            # image_height=CARD_HEIGHT,
            hit_box_algorithm="None",
        )
        if kind.endswith(("_n", "_w", "_s", "_e")):
            kind, _, direction = kind.rpartition("_")
            self.angle = {
                "e": 0,
                "s": 90,
                "w": 180,
                "n": 270,
            }[direction]
            self.directional = True
        self.append_texture(arcade.load_texture(f"{kind}.png"))
        if "_" in kind:
            # drop texture variation in kinds
            kind, *_ = kind.rpartition("_")
        self.kind = kind

    def turn_over(self):
        self.facing = "up"
        self.set_texture(1)
        self.scale = 0.5

    def can_kill(self, other_card, original_position):
        center_x, center_y = original_position
        if self.directional:
            if self.angle == 0:
                if center_x >= other_card.center_x:
                    raise ResetPosition(f"Hunter 0 {center_x} {other_card.center_x}")
                    return False
            elif self.angle == 90:
                if center_y >= other_card.center_y:
                    raise ResetPosition(f"Hunter 90 {center_x} {other_card.center_x}")
                    return False
            elif self.angle == 180:
                if center_x <= other_card.center_x:
                    raise ResetPosition(f"Hunter 180 {center_x} {other_card.center_x}")
                    return False
            elif self.angle == 270:
                if center_y <= other_card.center_y:
                    raise ResetPosition(f"Hunter 270 {center_x} {other_card.center_x}")
                    return False
        return other_card.kind in CARD_TYPES[self.kind].get("eats", [])


class Halali(arcade.Window):
    def __init__(self):
        super().__init__(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)

        self.place_list = None
        self.card_list = None
        self.held_card = None
        self.held_card_original_position = None
        self.to_play = None
        self.points = None
        self.animal_score = None
        self.human_score = None
        self.turn_counter = None
        self.tiled_revealed = None
        self.turns_left = None

    @property
    def accent_color(self):
        if self.to_play == "animals":
            return COLOR_ANIMALS
        if self.to_play == "humans":
            return COLOR_HUMANS

    def setup(self):
        arcade.set_background_color(arcade.color.AMAZON)
        self.points = {team: 0 for team in TEAMS}
        self.turns_left = None

        self.tiles_left = 3  # FIXME: N_ROWS * N_COLS - 1
        self.place_list = arcade.SpriteList()
        for x in range(N_COLS):
            for y in range(N_ROWS):
                place = arcade.SpriteSolidColor(
                    CARD_WIDTH - 20,
                    CARD_HEIGHT - 20,
                    arcade.csscolor.DARK_OLIVE_GREEN,
                )
                place.is_exit = False
                place.position = (
                    SCREEN_MARGIN + CARD_WIDTH / 2 + x * CARD_WIDTH,
                    SCREEN_MARGIN + CARD_HEIGHT / 2 + y * CARD_HEIGHT,
                )
                self.place_list.append(place)



        self.card_list = arcade.SpriteList()
        card_pile = iter(generate_pile())
        for x in range(N_COLS):
            for y in range(N_ROWS):
                if x == y == (N_COLS//2):
                    continue
                card = Card(next(card_pile))
                card.position = (
                    SCREEN_MARGIN + CARD_WIDTH / 2 + x * CARD_WIDTH,
                    SCREEN_MARGIN + CARD_HEIGHT / 2 + y * CARD_HEIGHT,
                )
                self.card_list.append(card)

        self.held_card = None
        self.held_card_original_position = None

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

        self.to_play = "animals"

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
            exit = arcade.SpriteSolidColor(
                CARD_WIDTH - 20,
                CARD_HEIGHT - 20,
                (102, 255, 0),
            )
            exit.is_exit = True
            exit.position = pos
            self.place_list.append(exit)

    def swap_teams(self):
        if self.turns_left is not None:
            if self.turns_left <= 0:
                print("End of game!")
                raise
            self.turns_left -= 0.5
        elif self.tiles_left == 0:
            self.add_exits()
            self.turns_left = 5
        self.to_play = "animals" if self.to_play == "humans" else "humans"

    def pull_to_top(self, card):
        self.card_list.remove(card)
        self.card_list.append(card)

    def on_draw(self):
        """ Render the screen. """
        # Clear the screen
        self.clear()
        self.place_list.draw()
        self.card_list.draw()
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
        self.human_score.text = str(self.points["humans"])
        self.human_score.draw()

        arcade.draw_rectangle_filled(
            0,
            0,
            TEXT_MARGIN * 4,
            TEXT_MARGIN * 4,
            color=COLOR_ANIMALS,
        )
        self.animal_score.text = str(self.points["animals"])
        self.animal_score.draw()

        # TODO: only if turns_left
        if self.turns_left is not None:
            arcade.draw_rectangle_filled(
                SCREEN_WIDTH // 2,
                SCREEN_HEIGHT + TEXT_MARGIN // 2,
                SCREEN_WIDTH // 2,
                TEXT_MARGIN * 4,
                color=self.accent_color,
            )
            self.turn_counter.text = f"{self.turns_left} turns left"
            self.turn_counter.draw()

    def on_mouse_press(self, x, y, button, key_modifiers):
        cards = arcade.get_sprites_at_point((x, y), self.card_list)
        if cards:
            card = cards[-1]
            if card.facing == "down":
                card.turn_over()
                self.tiles_left -= 1
                self.swap_teams()
                return
            if card.kind not in MOVABLE_FOR[self.to_play]:
                return
            self.held_card = cards[-1]
            self.held_card_original_position = self.held_card.position
            self.pull_to_top(self.held_card)

    def on_mouse_motion(self, x, y, dx, dy):
        if self.held_card:
            self.held_card.center_x += dx
            self.held_card.center_y += dy

    def on_mouse_release(self, x, y, button, key_modifiers):
        if self.held_card:
            place, distance = arcade.get_closest_sprite(self.held_card, self.place_list)
            try:
                if place.is_exit and CARD_TYPES[self.held_card.kind].get("team") != self.to_play:
                    raise ResetPosition("Can't rescue neutral pieces")
                if not arcade.check_for_collision(self.held_card, place):
                    # Not on a place
                    raise ResetPosition("Not intersecting with a place")

                if self.held_card_original_position == place.position:
                    raise ResetPosition("Already at this place")

                # find other card at that place
                cards_at_place = arcade.get_sprites_at_point((x, y), self.card_list)
                other_card = None
                allowed = {self.held_card}
                for card in cards_at_place:
                    if self.held_card == card:
                        continue
                    other_card = card
                    allowed.add(other_card)

                # Let's look for reasons we can't accept the input.
                # Are we not going straight?
                if not (
                    (self.held_card_original_position[0] == place.center_x)
                    or (self.held_card_original_position[1] == place.center_y)
                ):
                    raise ResetPosition("Can't go diagonally")

                if CARD_TYPES[self.held_card.kind].get("slow") and arcade.get_distance(
                    *self.held_card_original_position,
                    place.center_x,
                    place.center_y,
                ) > CARD_WIDTH:
                    raise ResetPosition(f"{self.held_card.kind} can only move 1 square")

                # Do we not have a clear path (other than ourselves and targets)?
                if not can_see(
                    self.held_card_original_position,
                    place.position,
                    allowed,
                    self.card_list,
                ):
                    raise ResetPosition("Not unobstructed")

                # Is the other card not edible?
                if other_card and not self.held_card.can_kill(
                    other_card,
                    self.held_card_original_position,
                ):
                    raise ResetPosition(f"Can't eat {other_card.kind}")

            except ResetPosition as e:
                print(e.args[0])
                self.held_card.position = self.held_card_original_position
            else:
                if other_card:
                    self.points[self.to_play] += CARD_TYPES[other_card.kind]["points"]
                    other_card.kill()
                if place.is_exit:
                    self.points[self.to_play] += CARD_TYPES[self.held_card.kind]["points"]
                    self.held_card.kill()
                else:
                    self.held_card.position = place.center_x, place.center_y
                self.swap_teams()
            finally:
                self.held_card = self.held_card_original_position = None


if __name__ == "__main__":
    window = Halali()
    window.setup()
    arcade.run()
