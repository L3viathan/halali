from importlib.metadata import version
__version__ = version("halali")
import arcade

from .ui import SetupView, SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE


def main():
    window = arcade.Window(SCREEN_WIDTH, SCREEN_HEIGHT, SCREEN_TITLE)
    start_view = SetupView()
    window.show_view(start_view)
    arcade.run()
