
class AsyncIter:
    def __init__(self, items):
        self.items = list(items)
    def __aiter__(self):
        return self
    async def __anext__(self):
        if not self.items:
            raise StopAsyncIteration
        return self.items.pop(0)
