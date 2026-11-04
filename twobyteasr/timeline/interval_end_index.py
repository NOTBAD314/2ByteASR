"""Bounded-work overlap search over intervals already sorted by start time."""


class IntervalEndIndex:
    """Range-max tree: skip whole groups whose intervals have all ended."""
    def __init__(self, ends=()):
        ends = tuple(int(value) for value in ends)
        self.count = len(ends)
        self.base = 1 << (max(1, self.count)-1).bit_length()
        tree = [float('-inf')] * (2*self.base)
        tree[self.base:self.base+self.count] = ends
        for node in range(self.base-1, 0, -1):
            tree[node] = max(tree[node*2], tree[node*2+1])
        self.tree = tuple(tree)

    def before_with_end_after(self, stop, cutoff):
        """Indices in ``[0, stop)`` with end > cutoff, in original order."""
        stop = min(self.count, max(0, int(stop)))
        if not stop or self.tree[1] <= cutoff:
            return ()
        result = []
        stack = [(1, 0, self.base)]
        while stack:
            node, left, right = stack.pop()
            if left >= stop or self.tree[node] <= cutoff:
                continue
            if right-left == 1:
                result.append(left)
                continue
            middle = (left+right)//2
            stack.append((node*2+1, middle, right))
            stack.append((node*2, left, middle))
        return tuple(result)
