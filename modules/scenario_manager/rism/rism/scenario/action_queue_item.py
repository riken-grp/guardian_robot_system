import time


class ActionQueueItem:
    def __init__(self, ret, opts):
        self.ret = ret
        self.opts = opts
        self.time = time.time()

    def __lt__(self, other):
        return self.time < other.time

    def get_item(self):
        return self.ret, self.opts
