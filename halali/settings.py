class Settings:
    def __init__(self):
        # TODO: load from file
        self.state = {
            "music": False,
            "sound": False,
            "indicators": False,
        }

    def dump(self):
        # TODO: also save to file
        return self.state.copy()

    def label(self, name):
        return {True: "yes", False: "no"}[self.state[name]]

    def click(self, name):
        self.state[name] = not self.state[name]
