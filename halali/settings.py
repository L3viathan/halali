import json
from pathlib import Path
from platformdirs import user_config_dir


class Settings:
    def __init__(self):
        self.config_path = Path(f"{user_config_dir('halali')}/config.json")
        self.state = {
            "music": False,
            "sound": False,
            "indicators": False,
        }
        try:
            with self.config_path.open() as f:
                self.state.update(json.load(f))
        except FileNotFoundError:
            pass

    def dump(self):
        self.config_path.parent.mkdir(exist_ok=True)
        with self.config_path.open("w") as f:
            json.dump(self.state, f)
        return self.state.copy()

    def label(self, name):
        return {True: "yes", False: "no"}[self.state[name]]

    def click(self, name):
        self.state[name] = not self.state[name]
